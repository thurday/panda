#!/usr/bin/env python

import sys
# Set log level to benefit from Scapy warnings
import logging
logging.getLogger("scapy.runtime").setLevel(logging.ERROR)
logging.getLogger("scapy.loading").setLevel(logging.ERROR)

from scapy.all import *

TLS_PORTS = set((443,4433))

VALID_TLS_VERSIONS = {
    (3,1): 'TLSv1.0',
    (3,2): 'TLSv1.1',
    (3,3): 'TLSv1.2',
}

CIPHER_SUITES = {
    "TLS_RSA_WITH_RC4_128_MD5": ("RC4", "MD5"),
    "TLS_RSA_WITH_RC4_128_SHA": ("RC4", "SHA1"),
    "TLS_RSA_WITH_DES_CBC_SHA": ("DES-CBC", "SHA1"),
    "TLS_RSA_WITH_3DES_EDE_CBC_SHA": ("DES-EDE3-CBC", "SHA1"),
    "TLS_DHE_DSS_WITH_DES_CBC_SHA": ("DES-CBC", "SHA1"),
    "TLS_DHE_DSS_WITH_3DES_EDE_CBC_SHA": ("DES-EDE3-CBC", "SHA1"),
    "TLS_DHE_RSA_WITH_DES_CBC_SHA": ("DES-CBC", "SHA1"),
    "TLS_DHE_RSA_WITH_3DES_EDE_CBC_SHA": ("DES-EDE3-CBC", "SHA1"),
    "TLS_RSA_WITH_AES_128_CBC_SHA": ("AES-128-CBC", "SHA1"),
    "TLS_DHE_DSS_WITH_AES_128_CBC_SHA": ("AES-128-CBC", "SHA1"),
    "TLS_DHE_RSA_WITH_AES_128_CBC_SHA": ("AES-128-CBC", "SHA1"),
    "TLS_RSA_WITH_AES_256_CBC_SHA": ("AES-256-CBC", "SHA1"),
    "TLS_DHE_DSS_WITH_AES_256_CBC_SHA": ("AES-256-CBC", "SHA1"),
    "TLS_DHE_RSA_WITH_AES_256_CBC_SHA": ("AES-256-CBC", "SHA1"),
    "TLS_RSA_WITH_CAMELLIA_128_CBC_SHA": ("CAMELLIA-128-CBC", "SHA1"),
    "TLS_DHE_DSS_WITH_CAMELLIA_128_CBC_SHA": ("CAMELLIA-128-CBC", "SHA1"),
    "TLS_DHE_RSA_WITH_CAMELLIA_128_CBC_SHA": ("CAMELLIA-128-CBC", "SHA1"),
    "TLS_RSA_WITH_CAMELLIA_256_CBC_SHA": ("CAMELLIA-256-CBC", "SHA1"),
    "TLS_DHE_DSS_WITH_CAMELLIA_256_CBC_SHA": ("CAMELLIA-256-CBC", "SHA1"),
    "TLS_DHE_RSA_WITH_CAMELLIA_256_CBC_SHA": ("CAMELLIA-256-CBC", "SHA1"),
}

def bidir_sessions(p):
    return "%s <-> %s" % tuple(sorted([
        p.sprintf("%IP.src%:%r,TCP.sport%"),
        p.sprintf("%IP.dst%:%r,TCP.dport%")
    ]))

pkts = rdpcap(sys.argv[1])
enc = pkts.filter(lambda p: "TCP" in p and (p.sport in TLS_PORTS or p.dport in TLS_PORTS))
sessions = enc.sessions(bidir_sessions)
successful = 0
for label, plist in sessions.items():
    info = {}
    for pkt in plist:
        if Raw not in pkt: continue
        client_send = pkt.dport in TLS_PORTS
        tls_rec = TLSv1RecordLayer(str(pkt[Raw]))
        if (tls_rec.major_version,tls_rec.minor_version) not in VALID_TLS_VERSIONS: continue
        else:
            info['version'] = VALID_TLS_VERSIONS[(tls_rec.major_version,tls_rec.minor_version)]
        if TLSv1ClientHello in tls_rec and 'client_random' not in info:
            hello = tls_rec[TLSv1ClientHello]
            date = struct.pack(">I", hello.unix_time)
            info['client_random'] = date + hello.random_bytes
        if TLSv1ServerHello in tls_rec and 'server_random' not in info:
            hello = tls_rec[TLSv1ServerHello]
            date = struct.pack(">I", hello.unix_time)
            info['server_random'] = date + hello.random_bytes
            info['cipher_suite'] = tls_rec.sprintf("%TLSv1ServerHello.cipher_suite%")
        # Get the first encrypted client message so we can test
        if client_send and 'client_enc' not in info:
            rec = tls_rec
            while TLSv1RecordLayer in rec:
                if rec[TLSv1RecordLayer].sprintf("%TLSv1RecordLayer.code%") == "CHANGE CIPHER SPEC":
                    handshake_finish = rec[TLSv1RecordLayer].payload
                    info['client_enc'] = (str(handshake_finish)[:1],str(handshake_finish)[1:3],str(handshake_finish)[5:])
                    break
                rec = rec[TLSv1RecordLayer].payload

    # Missing any components?
    failed = False
    for f in ('version','client_random', 'cipher_suite',
              'server_random','client_enc'):
        if f not in info:
            print "DEBUG: Session %s missing %s" % (label, f)
            failed = True
    if failed:
            plist.summary()
            continue

    print "# ==== %s ====" % label
    print "Client-Random: %s" % info['client_random'].encode('hex')
    print "Server-Random: %s" % info['server_random'].encode('hex')
    print "Content-Type:  %s" % info['client_enc'][0].encode('hex')
    print "Version:       %s" % info['client_enc'][1].encode('hex')
    print "Enc-Msg:       %s" % info['client_enc'][2].encode('hex')
    print "Cipher:        %s" % CIPHER_SUITES[info['cipher_suite']][0]
    print "MAC:           %s" % CIPHER_SUITES[info['cipher_suite']][1]

    successful += 1
print >>sys.stderr,"END: Found necessary info in %d of %d sessions." % (successful, len(sessions))
