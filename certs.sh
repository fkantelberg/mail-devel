#!/bin/bash
# Script to creating a with a CA signed client/server certificates

CURVE=prime256v1
DAYS=3650

mkdir -p pki/{ca,certs,private}

if [[ ! -f pki/ca/index.txt ]]; then
  touch pki/ca/index.txt
fi

if [[ ! -f pki/ca/serial ]]; then
  echo "01" > pki/ca/serial
fi

if [[ ! -f pki/private/ca.key ]]; then
  echo -e "\033[0;31mGenerating CA Key\033[0m"
  openssl ecparam -genkey -name "${CURVE}" -out pki/private/ca.key
fi

if [[ ! -f pki/ca.pem ]]; then
  echo -e "\033[0;31mGenerating CA Certificate\033[0m"
  openssl req -config openssl.cnf -batch -new -x509 -sha256 -key pki/private/ca.key -out pki/ca.pem
fi

if [[ ! -f pki/crl.pem ]]; then
  echo -e "\033[0;31mGenerating CRL\033[0m"
  openssl ca -config openssl.cnf -gencrl -out pki/crl.pem
fi

name="$1"
if [[ "$name" = "revoke" ]]; then
  name="$2"
  if [[ ! -z "${name}" ]]; then
    echo -e "\033[0;31mRevoking cert: ${name}\033[0m"
    openssl ca -config openssl.cnf -revoke "pki/${name}.pem"
    openssl ca -config openssl.cnf -gencrl -out pki/crl.pem
  fi
elif [[ ! -z "${name}" ]]; then
  if [[ ! -f "pki/${name}.key" ]]; then
    echo -e "\033[0;31mGenerating Key: ${name}\033[0m"
    openssl ecparam -genkey -name "${CURVE}" -out "pki/${name}.key"
  fi

  if [[ ! -f "pki/${name}.csr" ]]; then
    echo -e "\033[0;31mGenerating CSR: ${name}\033[0m"
    openssl req -config openssl.cnf -batch -new -sha256 -key "pki/${name}.key" -out "pki/${name}.csr"
  fi

  if [[ ! -f "pki/${name}.pem" ]]; then
    echo -e "\033[0;31mGenerating Cert: ${1}\033[0m"
    openssl ca -config openssl.cnf -batch -out "pki/${name}.pem" -infiles "pki/${name}.csr"
  fi
fi
