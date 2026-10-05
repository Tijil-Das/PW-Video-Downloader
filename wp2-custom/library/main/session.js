import "./forge.min.js";
import { AES_CMAC } from "./cmac.js"
import { Util } from "./util.js"

const { ClientIdentification, DrmCertificate, EncryptedClientIdentification, License, LicenseRequest,
    SignedDrmCertificate, SignedMessage, ProtocolVersion } = protobuf.roots.default.license_protocol;

const WIDEVINE_ROOT_PUBLIC_KEY = new Uint8Array([
    0x30, 0x82, 0x01, 0x8a, 0x02, 0x82, 0x01, 0x81, 0x00, 0xb4, 0xfe, 0x39, 0xc3, 0x65, 0x90, 0x03, 0xdb, 0x3c, 0x11, 0x97, 0x09, 0xe8, 0x68, 0xcd,
    0xf2, 0xc3, 0x5e, 0x9b, 0xf2, 0xe7, 0x4d, 0x23, 0xb1, 0x10, 0xdb, 0x87, 0x65, 0xdf, 0xdc, 0xfb, 0x9f, 0x35, 0xa0, 0x57, 0x03, 0x53, 0x4c, 0xf6,
    0x6d, 0x35, 0x7d, 0xa6, 0x78, 0xdb, 0xb3, 0x36, 0xd2, 0x3f, 0x9c, 0x40, 0xa9, 0x95, 0x26, 0x72, 0x7f, 0xb8, 0xbe, 0x66, 0xdf, 0xc5, 0x21, 0x98,
    0x78, 0x15, 0x16, 0x68, 0x5d, 0x2f, 0x46, 0x0e, 0x43, 0xcb, 0x8a, 0x84, 0x39, 0xab, 0xfb, 0xb0, 0x35, 0x80, 0x22, 0xbe, 0x34, 0x23, 0x8b, 0xab,
    0x53, 0x5b, 0x72, 0xec, 0x4b, 0xb5, 0x48, 0x69, 0x53, 0x3e, 0x47, 0x5f, 0xfd, 0x09, 0xfd, 0xa7, 0x76, 0x13, 0x8f, 0x0f, 0x92, 0xd6, 0x4c, 0xdf,
    0xae, 0x76, 0xa9, 0xba, 0xd9, 0x22, 0x10, 0xa9, 0x9d, 0x71, 0x45, 0xd6, 0xd7, 0xe1, 0x19, 0x25, 0x85, 0x9c, 0x53, 0x9a, 0x97, 0xeb, 0x84, 0xd7,
    0xcc, 0xa8, 0x88, 0x82, 0x20, 0x70, 0x26, 0x20, 0xfd, 0x7e, 0x40, 0x50, 0x27, 0xe2, 0x25, 0x93, 0x6f, 0xbc, 0x3e, 0x72, 0xa0, 0xfa, 0xc1, 0xbd,
    0x29, 0xb4, 0x4d, 0x82, 0x5c, 0xc1, 0xb4, 0xcb, 0x9c, 0x72, 0x7e, 0xb0, 0xe9, 0x8a, 0x17, 0x3e, 0x19, 0x63, 0xfc, 0xfd, 0x82, 0x48, 0x2b, 0xb7,
    0xb2, 0x33, 0xb9, 0x7d, 0xec, 0x4b, 0xba, 0x89, 0x1f, 0x27, 0xb8, 0x9b, 0x88, 0x48, 0x84, 0xaa, 0x18, 0x92, 0x0e, 0x65, 0xf5, 0xc8, 0x6c, 0x11,
    0xff, 0x6b, 0x36, 0xe4, 0x74, 0x34, 0xca, 0x8c, 0x33, 0xb1, 0xf9, 0xb8, 0x8e, 0xb4, 0xe6, 0x12, 0xe0, 0x02, 0x98, 0x79, 0x52, 0x5e, 0x45, 0x33,
    0xff, 0x11, 0xdc, 0xeb, 0xc3, 0x53, 0xba, 0x7c, 0x60, 0x1a, 0x11, 0x3d, 0x00, 0xfb, 0xd2, 0xb7, 0xaa, 0x30, 0xfa, 0x4f, 0x5e, 0x48, 0x77, 0x5b,
    0x17, 0xdc, 0x75, 0xef, 0x6f, 0xd2, 0x19, 0x6d, 0xdc, 0xbe, 0x7f, 0xb0, 0x78, 0x8f, 0xdc, 0x82, 0x60, 0x4c, 0xbf, 0xe4, 0x29, 0x06, 0x5e, 0x69,
    0x8c, 0x39, 0x13, 0xad, 0x14, 0x25, 0xed, 0x19, 0xb2, 0xf2, 0x9f, 0x01, 0x82, 0x0d, 0x56, 0x44, 0x88, 0xc8, 0x35, 0xec, 0x1f, 0x11, 0xb3, 0x24,
    0xe0, 0x59, 0x0d, 0x37, 0xe4, 0x47, 0x3c, 0xea, 0x4b, 0x7f, 0x97, 0x31, 0x1c, 0x81, 0x7c, 0x94, 0x8a, 0x4c, 0x7d, 0x68, 0x15, 0x84, 0xff, 0xa5,
    0x08, 0xfd, 0x18, 0xe7, 0xe7, 0x2b, 0xe4, 0x47, 0x27, 0x12, 0x11, 0xb8, 0x23, 0xec, 0x58, 0x93, 0x3c, 0xac, 0x12, 0xd2, 0x88, 0x6d, 0x41, 0x3d,
    0xc5, 0xfe, 0x1c, 0xdc, 0xb9, 0xf8, 0xd4, 0x51, 0x3e, 0x07, 0xe5, 0x03, 0x6f, 0xa7, 0x12, 0xe8, 0x12, 0xf7, 0xb5, 0xce, 0xa6, 0x96, 0x55, 0x3f,
    0x78, 0xb4, 0x64, 0x82, 0x50, 0xd2, 0x33, 0x5f, 0x91, 0x02, 0x03, 0x01, 0x00, 0x01
]);

export class Session {
    constructor(contentDecryptionModule) {
        this._deviceType = contentDecryptionModule.deviceType;
        this._devicePrivateKey = forge.pki.privateKeyFromPem(contentDecryptionModule.privateKey)
        this._identifierBlob = ClientIdentification.decode(contentDecryptionModule.identifierBlob)
    }

    setServiceCertificate(serviceCertificate) {
        const signedServiceCertificate = SignedDrmCertificate.decode(serviceCertificate)
        if (!this._verifyServiceCertificate(signedServiceCertificate)) {
            throw new Error("Service certificate is not signed by the Widevine root certificate")
        }
        this._serviceCertificate = signedServiceCertificate
    }

    generateAndroidIdentifier() {
        const randomBytes = Util.utf8.encode(forge.random.getBytesSync(4));
        return Util.utf8.encode(`${forge.util.bytesToHex(randomBytes).toUpperCase()}000000000100000000000000`)
    }

    generateGenericIdentifier() {
        return Util.utf8.encode(forge.random.getBytesSync(16))
    }

    getLicenseChallenge(messageBytes, encryptClientId) {
        let signedMessage;

        try {
            signedMessage = SignedMessage.decode(messageBytes);
        } catch (e) {
            return null;
        }

        if (signedMessage.type !== SignedMessage.MessageType.LICENSE_REQUEST) {
            throw new Error(`Cannot resign message of type ${signedMessage.type}`);
        }

        delete signedMessage.oemcryptoCoreMessage;

        const licenseRequest = LicenseRequest.decode(signedMessage.msg);

        delete licenseRequest.encryptedClientId;
        delete licenseRequest.clientId;

        if (!!encryptClientId) {
            if (this._serviceCertificate) {
                licenseRequest.encryptedClientId = this._encryptClientIdentification(
                    this._identifierBlob,
                    this._serviceCertificate
                );
            } else {
                licenseRequest.clientId = this._identifierBlob;
            }
        } else {
            licenseRequest.clientId = this._identifierBlob;
        }

        const isAndroid = this._deviceType === 2;
        const requestId = isAndroid
            ? this.generateAndroidIdentifier()
            : this.generateGenericIdentifier();

        licenseRequest.contentId.widevinePsshData.requestId = requestId;
        licenseRequest.protocolVersion = ProtocolVersion.VERSION_2_1;

        this._licenseRequest = LicenseRequest.encode(licenseRequest).finish();
        this._psshData = licenseRequest.contentId.widevinePsshData.psshData[0];

        const pss = forge.pss.create({
            md: forge.md.sha1.create(),
            mgf: forge.mgf.mgf1.create(forge.md.sha1.create()),
            saltLength: 20
        });

        const md = forge.md.sha1.create();
        md.update(Util.utf8.decode(this._licenseRequest), "raw");

        signedMessage.msg = this._licenseRequest;
        signedMessage.signature = Util.utf8.encode(this._devicePrivateKey.sign(md, pss));

        return {
            licenseRequest: SignedMessage.encode(signedMessage).finish(),
            requestId: Util.b64.encode(requestId)
        };
    }

    parseLicense(licenseBytes) {
        const signedMessage = SignedMessage.decode(licenseBytes);

        if (!this._licenseRequest) {
            throw new Error("please request a license first")
        }

        if (!signedMessage.sessionKey) {
            throw new Error("the license does not contain a session key")
        }
        if (!signedMessage.msg) {
            throw new Error("the license does not contain a message")
        }
        if (!signedMessage.signature) {
            throw new Error("the license does not contain a signature")
        }

        const sessionKey = this._devicePrivateKey.decrypt(
            Util.utf8.decode(signedMessage.sessionKey),
            "RSA-OAEP",
            {
                md: forge.md.sha1.create()
            }
        )

        const cmac = new AES_CMAC(Util.utf8.encode(sessionKey))
        const encKeyBase = new Uint8Array([
            ...Util.utf8.encode("ENCRYPTION"),
            ...new Uint8Array([0x00]),
            ...this._licenseRequest,
            ...new Uint8Array([0x00, 0x00, 0x00, 0x80])
        ])
        const authKeyBase = new Uint8Array([
            ...Util.utf8.encode("AUTHENTICATION"),
            ...new Uint8Array([0x00]),
            ...this._licenseRequest,
            ...new Uint8Array([0x00, 0x00, 0x02, 0x00])
        ])

        const encKey = cmac.calculate(
            new Uint8Array([
                ...new Uint8Array([0x01]),
                ...encKeyBase
            ])
        )

        const server_key_1 = cmac.calculate(new Uint8Array([
            ...new Uint8Array([0x01]),
            ...authKeyBase
        ]))
        const server_key_2 = cmac.calculate(new Uint8Array([
            ...new Uint8Array([0x02]),
            ...authKeyBase
        ]))
        const serverKey = new Uint8Array([
            ...new Uint8Array(server_key_1),
            ...new Uint8Array(server_key_2)
        ])

        const hmac = forge.hmac.create()
        hmac.start(forge.md.sha256.create(), Util.utf8.decode(serverKey), "raw")
        if (signedMessage.oemcryptoCoreMessage) {
            hmac.update(Util.utf8.decode(signedMessage.oemcryptoCoreMessage))
        }
        hmac.update(Util.utf8.decode(signedMessage.msg))
        const calculatedSignature = Util.utf8.encode(hmac.digest().data)

        if (!Util.sequenceEquals(calculatedSignature, signedMessage.signature)) {
            throw new Error("signatures do not match")
        }

        const license = License.decode(signedMessage.msg)

        const keyContainers = license.key.map(keyContainer => {
            if (keyContainer.type && keyContainer.type === 2 && keyContainer.key && keyContainer.iv) {
                const keyBuffer = forge.util.createBuffer(encKey, 'raw');
                const decipher = forge.cipher.createDecipher("AES-CBC", keyBuffer)

                decipher.start({
                    iv: Util.utf8.decode(keyContainer.iv)
                })
                decipher.update(forge.util.createBuffer(keyContainer.key))
                decipher.finish()

                return {
                    kid: keyContainer.id.length !== 0 ? forge.util.bytesToHex(keyContainer.id) : "00000000000000000000000000000000",
                    k: forge.util.bytesToHex(Util.utf8.encode(decipher.output.data))
                }
            }
        })
        const valid_containers = keyContainers.filter(container => !!container);
        if (valid_containers.length < 1) {
            throw new Error("there was not a single valid key in the response")
        }
        return valid_containers;
    }

    _encryptClientIdentification(clientIdentification, signedServiceCertificate) {
        if (!signedServiceCertificate.drmCertificate) {
            throw new Error("the service certificate does not contain an actual certificate")
        }

        const serviceCertificate = DrmCertificate.decode(
            signedServiceCertificate.drmCertificate
        )

        if (!serviceCertificate.publicKey) {
            throw new Error("the service certificate does not contain a public key")
        }

        const key = forge.random.getBytesSync(16)
        const iv = forge.random.getBytesSync(16)

        const cipher = forge.cipher.createCipher("AES-CBC", key)
        cipher.start({
            iv: iv
        })
        cipher.update(
            forge.util.createBuffer(
                ClientIdentification.encode(clientIdentification).finish()
            )
        )
        cipher.finish()
        const rawEncryptedClientIdentification = Util.utf8.encode(cipher.output.data)

        const publicKey = forge.pki.publicKeyFromAsn1(
            forge.asn1.fromDer(
                Util.utf8.decode(serviceCertificate.publicKey)
            )
        )
        const encryptedKey = publicKey.encrypt(key, "RSA-OAEP", {
            md: forge.md.sha1.create()
        })

        return new EncryptedClientIdentification({
            encryptedClientId: rawEncryptedClientIdentification,
            encryptedClientIdIv: Util.utf8.encode(iv),
            encryptedPrivacyKey: Util.utf8.encode(encryptedKey),
            providerId: serviceCertificate.providerId,
            serviceCertificateSerialNumber: serviceCertificate.serialNumber
        })
    }

    _verifyServiceCertificate(signedServiceCertificate) {
        if (!signedServiceCertificate.drmCertificate) {
            throw new Error("the service certificate does not contain an actual certificate")
        }
        if (!signedServiceCertificate.signature) {
            throw new Error("the service certificate does not contain a signature")
        }

        const pss = forge.pss.create({
            md: forge.md.sha1.create(),
            mgf: forge.mgf.mgf1.create(forge.md.sha1.create()),
            saltLength: 20
        })

        const sha1 = forge.md.sha1.create()
        sha1.update(
            Util.utf8.decode(signedServiceCertificate.drmCertificate),
            "raw"
        )

        const publicKey = forge.pki.publicKeyFromAsn1(
            forge.asn1.fromDer(
                Util.utf8.decode(WIDEVINE_ROOT_PUBLIC_KEY)
            )
        )

        return publicKey.verify(
            sha1.digest().bytes(),
            Util.utf8.decode(signedServiceCertificate.signature),
            pss
        )
    }

    getPsshData() {
        if (!this._psshData)
            throw new Error("please request a license first")

        return this._psshData;
    }
}
