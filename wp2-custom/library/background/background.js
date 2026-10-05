import { RemoteCdm } from "./remote_cdm.js";

const SCRIPT_CONFIGS = [
    {
        id: "WVP2_ISOLATED",
        matches: ["<all_urls>"],
        js: ["library/isolated/bundle.min.js"],
        runAt: "document_start",
        world: "ISOLATED",
        allFrames: true,
        matchOriginAsFallback: true,
        persistAcrossSessions: true,
    },
    {
        id: "WVP2_MAIN",
        matches: ["<all_urls>"],
        js: ["library/main/bundle.min.js"],
        runAt: "document_start",
        world: "MAIN",
        allFrames: true,
        matchOriginAsFallback: true,
        persistAcrossSessions: true,
    }
];

let isOutdated = false;

async function setIsOutdated() {
    const projectBase = "https://github.com/DevLARLEY/WidevineProxy2/releases/"

    const response = await fetch(projectBase + "latest");
    const lastestVersion = response.url.replace(projectBase + "tag/v", "");

    let currentVersion = "";
    try {
        currentVersion = chrome.runtime.getManifest().version;
    } catch (e) {}

    console.log("latest", lastestVersion, "current", currentVersion);

    isOutdated =
        parseInt(lastestVersion.replaceAll(".", "")) >
        parseInt(currentVersion.replaceAll(".", ""));
}

let registrationPromise = null;

async function getEnabledState() {
    const { enabled } = await chrome.storage.sync.get("enabled");
    const { selected } = await chrome.storage.sync.get("selected");
    return !!(enabled ?? true) && !!selected;
}

async function registerScripts() {
    const existing = await chrome.scripting.getRegisteredContentScripts();
    const existingIds = new Set(existing.map((s) => s.id));

    const toRegister = SCRIPT_CONFIGS.filter((cfg) => !existingIds.has(cfg.id));
    const toUpdate = SCRIPT_CONFIGS.filter((cfg) => existingIds.has(cfg.id));

    if (toRegister.length) {
        await chrome.scripting.registerContentScripts(toRegister);
    }
    if (toUpdate.length) {
        await chrome.scripting.updateContentScripts(toUpdate);
    }
}

async function unregisterScripts() {
    const existing = await chrome.scripting.getRegisteredContentScripts();
    const existingIds = new Set(existing.map((s) => s.id));

    const ids = SCRIPT_CONFIGS.map((cfg) => cfg.id).filter((id) => existingIds.has(id));

    if (ids.length) {
        await chrome.scripting.unregisterContentScripts({ ids });
    }
}

async function ensureScriptsRegistered() {
    if (registrationPromise) {
        return registrationPromise;
    }

    registrationPromise = (async () => {
        try {
            const enabled = await getEnabledState();
            if (enabled) {
                await registerScripts();
            } else {
                await unregisterScripts();
            }
        } finally {
            registrationPromise = null;
        }
    })();

    return registrationPromise;
}

function openPicker(path, mobile) {
    if (mobile) {
        chrome.tabs.create({ url: chrome.runtime.getURL(path) });
    } else {
        chrome.windows.create({ url: path, type: "popup", width: 320, height: 180 });
    }
}

const remoteCdmSessions = new Map();

async function getRemoteDevice() {
    const { selected_remote_cdm } = await chrome.storage.sync.get(["selected_remote_cdm"]);

    if (!selected_remote_cdm)
        throw new Error("No remote CDM selected");

    const deviceObj = await chrome.storage.sync.get([selected_remote_cdm]);
    const device = deviceObj[selected_remote_cdm];

    if (!device)
        throw new Error(`Selected remote CDM "${selected_remote_cdm}" not found in storage`);

    return device;
}

function getRemoteCdm(sessionId) {
    const cdm = remoteCdmSessions.get(sessionId);
    if (!cdm)
        throw new Error(`Unknown remote CDM session "${sessionId}"`);
    return cdm;
}

async function handleRemoteMessage(type, payload) {
    switch (type) {
        case "REMOTE_OPEN": {
            const device = await getRemoteDevice();
            const cdm = await RemoteCdm.open(device.host, device.secret, device.device_name);
            remoteCdmSessions.set(cdm.sessionId, cdm);
            return cdm.sessionId;
        }
        case "REMOTE_SET_SERVICE_CERTIFICATE": {
            const cdm = getRemoteCdm(payload.sessionId);
            await cdm.setServiceCertificate(payload.certificate);
            return true;
        }
        case "REMOTE_GET_CHALLENGE": {
            const cdm = getRemoteCdm(payload.sessionId);
            return await cdm.getLicenseChallenge(payload.initData, payload.privacyMode);
        }
        case "REMOTE_PARSE": {
            const cdm = getRemoteCdm(payload.sessionId);
            try {
                // parse_license closes the session server-side, so close it here
                return await cdm.parseLicense(payload.license);
            } finally {
                remoteCdmSessions.delete(payload.sessionId);
            }
        }
        default:
            throw new Error(`Unknown remote message type "${type}"`);
    }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (!message || typeof message.type !== "string" || !message.type.startsWith("REMOTE_"))
        return;

    handleRemoteMessage(message.type, message.payload)
        .then((data) => sendResponse({ data }))
        .catch((error) => sendResponse({ error: error?.message || String(error) }));

    return true; // keep the message channel open for the async sendResponse
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    switch (message && message.type) {
        case "OPEN_PICKER_WVD":
            openPicker("picker/wvd/filePicker.html", false);
            break;
        case "OPEN_PICKER_WVD_MOBILE":
            openPicker("picker/wvd/filePicker.html", true);
            break;
        case "OPEN_PICKER_REMOTE":
            openPicker("picker/remote/filePicker.html", false);
            break;
        case "OPEN_PICKER_REMOTE_MOBILE":
            openPicker("picker/remote/filePicker.html", true);
            break;
        case "IS_OUTDATED":
            sendResponse(isOutdated);
            break;
    }
});

chrome.webRequest.onBeforeSendHeaders.addListener(
    async (details)=> {
        if (details.tabId === -1)
            return;
        if (details.method !== "GET")
            return;

        const headers = details.requestHeaders
            .filter(item => !(
                item.name.startsWith('sec-ch-ua') ||
                item.name.startsWith('Sec-Fetch') ||
                item.name.startsWith('Accept-') ||
                item.name.startsWith('Host') ||
                item.name === "Connection"
            )).reduce((acc, item) => {
                acc[item.name] = item.value;
                return acc;
            }, {});

        try {
            await chrome.tabs.sendMessage(details.tabId, {
                type: "MANIFEST_HEADERS",
                payload: {
                    url: details.url,
                    headers: headers
                }
            })
        } catch (e) {
            // ignored
        }
    },
    {urls: ["<all_urls>"]},
    ['requestHeaders', chrome.webRequest.OnSendHeadersOptions.EXTRA_HEADERS].filter(Boolean)
);

chrome.runtime.onInstalled.addListener(() => {
    ensureScriptsRegistered();
});

chrome.runtime.onStartup.addListener(() => {
    ensureScriptsRegistered();
});

async function setIcon(type) {
    const p = type === "red" ? "-red" : "";
    await chrome.action.setIcon({
        path: {
            16: `../../images/icon-16${p}.png`,
            32: `../../images/icon-32${p}.png`,
            64: `../../images/icon-64${p}.png`,
            128: `../../images/icon-128${p}.png`,
        }
    });
}

let timeoutId = null;

chrome.storage.onChanged.addListener(async (changes, areaName) => {
    if (areaName === "local") {
        const added = Object.values(changes).some(
            ({ oldValue, newValue }) =>
                oldValue === undefined && newValue !== undefined
        );

        if (added) {
            await setIcon("red");

            if (timeoutId)
                clearTimeout(timeoutId);

            timeoutId = setTimeout(async () => {
                timeoutId = null;
                await setIcon("normal");
            }, 60 * 1000);
        }
    } else if (areaName === "sync") {
        ensureScriptsRegistered();
    }
});

chrome.runtime.onSuspend.addListener(async () => {
    await setIcon("normal");
});

setTimeout(() => {
    ensureScriptsRegistered();
    setIsOutdated();
    setInterval(setIsOutdated, 12 * 60 * 60 * 1000); // 12 hours
}, 1000);

