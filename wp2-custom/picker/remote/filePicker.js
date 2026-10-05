const input = document.getElementById("fileInput");
const status = document.getElementById("status");

function displayName(cdm) {
    const hostUrl = new URL(cdm.host);
    return `${cdm.device_name} (L${cdm.security_level}/${cdm.system_id}) @ ${hostUrl.hostname}`;
}

input.addEventListener("change", async () => {
    const file = input.files && input.files[0];
    if (!file)
        return;

    try {
        const cdm = JSON.parse(await file.text());
        const name = displayName(cdm);

        chrome.storage.sync.get(null, (s) => {
            const remotes = (s.remote_cdms || []).filter((n) => n !== name);
            remotes.push(name);
            chrome.storage.sync.set(
                { [name]: cdm, remote_cdms: remotes, selected_remote_cdm: name },
                () => window.close()
            );
        });
    } catch (e) {
        status.textContent = "Invalid remote.json: " + e.message;
        status.className = "err";
    }
});
