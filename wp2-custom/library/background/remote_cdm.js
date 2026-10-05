export class RemoteCdm {
    constructor(sessionId, host, secret, deviceName) {
        this.sessionId = sessionId;
        this.host = host;
        this.secret = secret;
        this.deviceName = deviceName;
    }

    static async open(host, secret, deviceName) {
        const trimmedHost = host.replace(/\/+$/, "");

        const openResponse = await fetch(
            `${trimmedHost}/${deviceName}/open`,
            {
                method: 'GET',
                headers: {
                    "X-Secret-Key": secret
                }
            }
        );

        if (openResponse.status !== 200)
            throw new Error(`Remote CDM API (open) response code does not indicate success`);

        const responseJson = await openResponse.json();
        const sessionId = responseJson.data.session_id;

        return new RemoteCdm(sessionId, trimmedHost, secret, deviceName);
    }

    async setServiceCertificate(certificateB64) {
        const certificateResponse = await fetch(
            `${this.host}/${this.deviceName}/set_service_certificate`,
            {
                method: "POST",
                headers: {
                    "content-type": "application/json",
                    "X-Secret-Key": this.secret
                },
                body: JSON.stringify({
                    session_id: this.sessionId,
                    certificate: certificateB64
                })
            }
        );

        if (certificateResponse.status !== 200)
            throw new Error(`Remote CDM API (set_service_certificate) response code does not indicate success`);
    }

    async getLicenseChallenge(initDataB64, privacyMode) {
        const challengeResponse = await fetch(
            `${this.host}/${this.deviceName}/get_license_challenge/STREAMING`,
            {
                method: "POST",
                headers: {
                    "content-type": "application/json",
                    "X-Secret-Key": this.secret
                },
                body: JSON.stringify({
                    session_id: this.sessionId,
                    init_data: initDataB64,
                    privacy_mode: privacyMode
                })
            }
        )

        if (challengeResponse.status !== 200)
            throw new Error(`Remote CDM API (get_license_challenge) response code does not indicate success`);

        const responseJson = await challengeResponse.json();
        return responseJson.data.challenge_b64;
    }

    async parseLicense(licenseB64) {
        const parseResponse = await fetch(
            `${this.host}/${this.deviceName}/parse_license`,
            {
                method: "POST",
                headers: {
                    "content-type": "application/json",
                    "X-Secret-Key": this.secret
                },
                body: JSON.stringify({
                    session_id: this.sessionId,
                    license_message: licenseB64
                })
            }
        )

        if (parseResponse.status !== 200)
            throw new Error(`Remote CDM API (parse_license) response code does not indicate success`);

        const keysResponse = await fetch(
            `${this.host}/${this.deviceName}/get_keys/CONTENT`,
            {
                method: "POST",
                headers: {
                    "content-type": "application/json",
                    "X-Secret-Key": this.secret
                },
                body: JSON.stringify({
                    session_id: this.sessionId
                })
            }
        )

        if (keysResponse.status !== 200)
            throw new Error(`Remote CDM API (get_keys) response code does not indicate success`);

        const responseJson = await keysResponse.json();
        const keys = responseJson.data.keys;

        await fetch(
            `${this.host}/${this.deviceName}/close/${this.sessionId}`,
            {
                method: 'GET',
                headers: {
                    "X-Secret-Key": this.secret
                }
            }
        );

        return keys.map(({ key, key_id }) => ({ k: key, kid: key_id }));
    }
}
