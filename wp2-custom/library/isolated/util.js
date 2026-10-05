export class Util {
    static b64 = {
        /* b64 String -> Uint8Array */
        decode: s => Uint8Array.from(atob(s), c => c.charCodeAt(0)),
        /* Uint8Array -> b64 String */
        encode: b => btoa(String.fromCharCode(...new Uint8Array(b)))
    };

    static readWidevineDevice(b64Data) {
        const data = Util.b64.decode(b64Data);
        const deviceType = data[4];
        let base = 7;

        const keyLen = (data[base++] << 8) | data[base++];
        const key = data.subarray(base, base + keyLen);
        base += keyLen;
        const idLen = (data[base++] << 8) | data[base++];
        const id = data.subarray(base, base + idLen);

        return {
            deviceType: deviceType,
            privateKey: Util.b64.encode(key),
            clientId: Util.b64.encode(id)
        }
    }
}