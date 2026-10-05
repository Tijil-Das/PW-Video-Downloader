import { Util } from "./util.js";

const handlers = new Map();
const manifestUrls = new Map();
const manifestHeaders = new Map();
const emeStatuses = {};

function onMessage(type, handler) {
    handlers.set(type, handler);
}

function relayToBackground(type) {
    onMessage(type, async (payload) => {
        const response = await chrome.runtime.sendMessage({ type, payload });
        if (response && response.error)
            throw new Error(response.error);
        return response ? response.data : undefined;
    });
}

relayToBackground("REMOTE_OPEN");
relayToBackground("REMOTE_SET_SERVICE_CERTIFICATE");
relayToBackground("REMOTE_GET_CHALLENGE");
relayToBackground("REMOTE_PARSE");

onMessage("SETTINGS", async _ => {
    const settings = await chrome.storage.sync.get(["selected", "selected_remote_cdm", "server_cert", "proxy_mode", "device_type"]);

    if (!settings)
        return;

    const deviceType = settings.device_type ?? "WVD";

    let device;

    if (deviceType === "WVD") {
        const deviceObj = await chrome.storage.sync.get([settings.selected]);
        device = Util.readWidevineDevice(deviceObj[settings.selected]);
    } else if (deviceType === "REMOTE") {
        const deviceObj = await chrome.storage.sync.get([settings.selected_remote_cdm]);
        device = deviceObj[settings.selected_remote_cdm];
    }

    return {
        device: device,
        device_type: deviceType,
        server_cert: settings.server_cert ?? false,
        proxy_mode: settings.proxy_mode ?? "event"
    }
});

onMessage("MANIFEST_URL", async (data) => {
    const { url, tab_url } = data;
    delete data.tab_url;

    if (!manifestUrls.has(tab_url)) {
        manifestUrls.set(tab_url, [data]);
    } else {
        let elements = manifestUrls.get(tab_url);
        if (!elements.some(e => e.url === url)) {
            elements.push(data);
            manifestUrls.set(tab_url, elements);
        }
    }
})

onMessage("KEYS", async (data) => {
    try {
        if (manifestUrls.has(data.url)) {
            const urls = manifestUrls.get(data.url);
            urls.forEach(e => {
                if (manifestHeaders.has(e.url)) {
                    e.headers = manifestHeaders.get(e.url);
                }
            })
            if (!!urls)
                data.manifests = urls;
        }
    } catch (e) {
        console.error("KEY handler failed", e);
        throw e;
    }

    await chrome.storage.local.set({ [data.pssh_data]: data })
});

function onEmeStatusMessage(type) {
    onMessage(type, (data) => {
        emeStatuses[type] = data;
        chrome.runtime.sendMessage({
            type: "EME_STATUS_REACTIVE",
            payload: {
                type: type,
                data: data
            }
        });
    });
}

onEmeStatusMessage("EME_CREATE_MEDIA_KEYS");
onEmeStatusMessage("EME_CREATE_SESSION");
onEmeStatusMessage("EME_GENERATE_REQUEST");
onEmeStatusMessage("EME_LICENSE_REQUEST");
onEmeStatusMessage("EME_LICENSE");

document.addEventListener('__ext_response', async (event) => {
    const detail = structuredClone(event.detail); // I don't know, this is needed in Firefox on Android
    const { type, body, requestId } = detail;

    const handler = handlers.get(type);

    let responseBody = null;
    let error = null;

    if (!handler) {
        error = `No handler registered for type "${type}"`;
    } else {
        try {
            responseBody = await handler(body);
        } catch (err) {
            error = err?.message || String(err);
        }
    }

    function dispatchToPage(eventName, detail) {
        if (typeof cloneInto === 'function') {
            const win = window.wrappedJSObject;
            const clonedDetail = cloneInto(detail, win);
            const ev = new win.CustomEvent(eventName, cloneInto({ detail: clonedDetail }, win));
            document.dispatchEvent(ev);
        } else {
            document.dispatchEvent(new CustomEvent(eventName, { detail }));
        }
    }

    dispatchToPage('__ext_responseReceived', {
        requestId,
        body: responseBody,
        error,
    });
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === "MANIFEST_HEADERS") {
        const { url, headers } = message.payload;
        manifestHeaders.set(url, headers);
    } else if (message.type === "EME_STATUS_ACTIVE") {
        if (Object.keys(emeStatuses).length > 0) {
            sendResponse(emeStatuses);
        }
    }
});