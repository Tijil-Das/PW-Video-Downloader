const input = document.getElementById("fileInput");
const status = document.getElementById("status");

function toBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = "";
    const chunk = 0x8000;
    for (let i = 0; i < bytes.length; i += chunk) {
        binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
    }
    return btoa(binary);
}

input.addEventListener("change", async () => {
    const file = input.files && input.files[0];
    if (!file) return;
    try {
        const b64 = toBase64(await file.arrayBuffer());
        const name = file.name.replace(/\.wvd$/i, "");
        chrome.storage.sync.get(null, (s) => {
            const devices = (s.devices || []).filter((n) => n !== name);
            devices.push(name);
            chrome.storage.sync.set(
                { [name]: b64, devices, selected: name },
                () => window.close()
            );
        });
    } catch (e) {
        status.textContent = "Failed to read file: " + e.message;
        status.className = "err";
    }
});
