#!/usr/bin/env python3

import sys
if sys.version_info.major < 3:
    sys.stderr.write('Sorry, Python 3.x required by this example.\n')
    sys.exit(1)

import bitcoin
import bitcoin.rpc
from bitcoin import SelectParams
from bitcoin.core import b2x, lx, b2lx, x, COIN, COutPoint, CMutableTxOut, CMutableTxIn, CMutableTransaction, Hash160, CTransaction
from bitcoin.base58 import decode
from bitcoin.core.script import CScript, OP_DUP, OP_IF, OP_ELSE, OP_ENDIF, OP_HASH160, OP_EQUALVERIFY, OP_CHECKSIG, SignatureHash, SIGHASH_ALL, OP_FALSE, OP_DROP, OP_CHECKLOCKTIMEVERIFY, OP_SHA256, OP_TRUE
from bitcoin.core.scripteval import VerifyScript, SCRIPT_VERIFY_P2SH
from bitcoin.wallet import CBitcoinAddress, CBitcoinSecret, P2SHBitcoinAddress, P2PKHBitcoinAddress

from xcat.utils import *

import zcash
import zcash.rpc
import pprint, json

from xcat.zcashRPC import parse_script

# SelectParams('testnet')
SelectParams('regtest')
# TODO: Accurately read user and pw info
bitcoind = bitcoin.rpc.Proxy(service_url="http://user:password@127.0.0.1:18332")
FEE = 0.001*COIN


def validateaddress(addr):
    return bitcoind.validateaddress(addr)

def parse_secret(txid):
    decoded = bitcoind.getrawtransaction(lx(txid), 1)
    print("Decoded", decoded)
    # decoded = bitcoind.decoderawtransaction(raw)
    asm = decoded['vin'][0]['scriptSig']['asm'].split(" ")
    print(asm[2])

def get_keys(funder_address, redeemer_address):
    fundpubkey = CBitcoinAddress(funder_address)
    redeempubkey = CBitcoinAddress(redeemer_address)
    # fundpubkey = bitcoind.getnewaddress()
    # redeempubkey = bitcoind.getnewaddress()
    return fundpubkey, redeempubkey

def privkey(address):
    bitcoind.dumpprivkey(address)

def hashtimelockcontract(funder, redeemer, commitment, locktime):
    funderAddr = CBitcoinAddress(funder)
    redeemerAddr = CBitcoinAddress(redeemer)
    if type(commitment) == str:
        commitment = x(commitment)
    # h = sha256(secret)
    blocknum = bitcoind.getblockcount()
    print("Current blocknum", blocknum)
    redeemblocknum = blocknum + locktime
    print("REDEEMBLOCKNUM BITCOIN", redeemblocknum)
    print("COMMITMENT", commitment)
    redeemScript = CScript([OP_IF, OP_SHA256, commitment, OP_EQUALVERIFY,OP_DUP, OP_HASH160,
                                 redeemerAddr, OP_ELSE, redeemblocknum, OP_CHECKLOCKTIMEVERIFY, OP_DROP, OP_DUP, OP_HASH160,
                                 funderAddr, OP_ENDIF,OP_EQUALVERIFY, OP_CHECKSIG])
    print("Redeem script for p2sh contract on Bitcoin blockchain:", b2x(redeemScript))
    txin_scriptPubKey = redeemScript.to_p2sh_scriptPubKey()
    # Convert the P2SH scriptPubKey to a base58 Bitcoin address
    txin_p2sh_address = CBitcoinAddress.from_scriptPubKey(txin_scriptPubKey)
    p2sh = str(txin_p2sh_address)
    print("p2sh computed", p2sh)
    return {'p2sh': p2sh, 'redeemblocknum': redeemblocknum, 'redeemScript': b2x(redeemScript), 'redeemer': redeemer, 'funder': funder, 'locktime': locktime}

def fund_htlc(p2sh, amount):
    send_amount = float(amount) * COIN
    fund_txid = bitcoind.sendtoaddress(p2sh, send_amount)
    txid = b2x(lx(b2x(fund_txid)))
    return txid

def check_funds(p2sh):
    bitcoind.importaddress(p2sh, "", False)
    # Get amount in address
    amount = bitcoind.getreceivedbyaddress(p2sh, 0)
    amount = amount/COIN
    return amount

## TODO: FIX search for p2sh in block
def search_p2sh(block, p2sh):
    print("Fetching block...")
    blockdata = bitcoind.getblock(lx(block))
    print("done fetching block")
    txs = blockdata.vtx
    print("txs", txs)
    for tx in txs:
        txhex = b2x(tx.serialize())
        # Using my fork of python-zcashlib to get result of decoderawtransaction
        txhex = txhex + '00'
        rawtx = zcashd.decoderawtransaction(txhex)
        # print('rawtx', rawtx)
        print(rawtx)
        for vout in rawtx['vout']:
            if 'addresses' in vout['scriptPubKey']:
                for addr in vout['scriptPubKey']['addresses']:
                    print("Sent to address:", addr)
                    if addr == p2sh:
                        print("Address to p2sh found in transaction!", addr)
    print("Returning from search_p2sh")

def get_tx_details(txid):
    # must convert txid string to bytes x(txid)
    fund_txinfo = bitcoind.gettransaction(lx(txid))
    return fund_txinfo['details'][0]

# redeems automatically after buyer has funded tx, by scanning for transaction to the p2sh
# i.e., doesn't require buyer telling us fund txid
def auto_redeem(contract, secret):
    print("Parsing script for auto_redeem...")
    scriptarray = parse_script(contract.redeemScript)
    redeemblocknum = scriptarray[8]
    redeemPubKey = P2PKHBitcoinAddress.from_bytes(x(scriptarray[6]))
    refundPubKey = P2PKHBitcoinAddress.from_bytes(x(scriptarray[13]))
    # How to find redeemScript and redeemblocknum from blockchain?
    print("Contract in auto redeem", contract.__dict__)
    p2sh = contract.p2sh
    #checking there are funds in the address
    amount = check_funds(p2sh)
    if(amount == 0):
        print("address ", p2sh, " not funded")
        quit()
    fundtx = find_transaction_to_address(p2sh)
    amount = fundtx['amount'] / COIN
    print("Found fundtx:", fundtx)
    p2sh = P2SHBitcoinAddress(p2sh)
    if fundtx['address'] == p2sh:
        print("Found {0} in p2sh {1}, redeeming...".format(amount, p2sh))

        # Parsing redeemblocknum from the redeemscript of the p2sh
        # redeemblocknum = find_redeemblocknum(contract)
        blockcount = bitcoind.getblockcount()
        print("\nCurrent blocknum at time of redeem on Bitcoin:", blockcount)
        if blockcount < int(redeemblocknum):
            # redeemPubKey = find_redeemAddr(contract)
            print('redeemPubKey', redeemPubKey)
        else:
            print("nLocktime exceeded, refunding")
            # refundPubKey = find_refundAddr(contract)
            redeemPubKey = refundPubkey
            print('refundPubKey', redeemPubKey)
        # redeemPubKey = CBitcoinAddress.from_scriptPubKey(redeemPubKey)
        # exit()

        zec_redeemScript = CScript(x(contract.redeemScript))
        txin = CMutableTxIn(fundtx['outpoint'])
        txout = CMutableTxOut(fundtx['amount'] - FEE, redeemPubKey.to_scriptPubKey())
        # Create the unsigned raw transaction.
        tx = CMutableTransaction([txin], [txout])
        # nLockTime needs to be at least as large as parameter of CHECKLOCKTIMEVERIFY for script to verify
        # TODO: these things like redeemblocknum should really be properties of a tx class...
        # Need: redeemblocknum, zec_redeemScript, secret (for creator...), txid, redeemer...
        if blockcount >= int(redeemblocknum):
            print("\nLocktime exceeded")
            tx.nLockTime = redeemblocknum  # Ariel: This is only needed when redeeming with the timelock
        sighash = SignatureHash(zec_redeemScript, tx, 0, SIGHASH_ALL)
        # TODO: figure out how to better protect privkey
        privkey = bitcoind.dumpprivkey(redeemPubKey)
        sig = privkey.sign(sighash) + bytes([SIGHASH_ALL])
        print("SECRET", secret)
        preimage = secret.encode('utf-8')
        txin.scriptSig = CScript([sig, privkey.pub, preimage, OP_TRUE, zec_redeemScript])

        # exit()

        print("txin.scriptSig", b2x(txin.scriptSig))
        txin_scriptPubKey = zec_redeemScript.to_p2sh_scriptPubKey()
        print('Redeem txhex', b2x(tx.serialize()))
        VerifyScript(txin.scriptSig, txin_scriptPubKey, tx, 0, (SCRIPT_VERIFY_P2SH,))
        print("script verified, sending raw tx")
        txid = bitcoind.sendrawtransaction(tx)
        print("Txid of submitted redeem tx: ", b2x(lx(b2x(txid))))
        return  b2x(lx(b2x(txid)))
    else:
        print("No contract for this p2sh found in database", p2sh)

def redeem_contract(contract, secret):
    # How to find redeemScript and redeemblocknum from blockchain?
    print("Contract in redeem_contract", contract.__dict__)
    p2sh = contract.p2sh
    #checking there are funds in the address
    amount = check_funds(p2sh)
    if(amount == 0):
        print("address ", p2sh, " not funded")
        quit()
    fundtx = find_transaction_to_address(p2sh)
    amount = fundtx['amount'] / COIN
    print("Found fundtx:", fundtx)
    p2sh = P2SHBitcoinAddress(p2sh)
    if fundtx['address'] == p2sh:
        print("Found {0} in p2sh {1}, redeeming...".format(amount, p2sh))

        # TODO: Decodescript is not working, add back in.
        # redeemblocknum = find_redeemblocknum(contract)

        blockcount = bitcoind.getblockcount()
        print("\nCurrent blocknum at time of redeem on Zcash:", blockcount)
        if blockcount < contract.redeemblocknum:

            # redeemPubKey = find_redeemAddr(contract)
            redeemPubKey = P2PKHBitcoinAddress.from_bytes(x('7788b4511a25fba1092e67b307a6dcdb6da125d9'))

            print('redeemPubKey', redeemPubKey)
            zec_redeemScript = CScript(x(contract.redeemScript))
            txin = CMutableTxIn(fundtx['outpoint'])
            txout = CMutableTxOut(fundtx['amount'] - FEE, redeemPubKey.to_scriptPubKey())
            # Create the unsigned raw transaction.
            tx = CMutableTransaction([txin], [txout])
            sighash = SignatureHash(zec_redeemScript, tx, 0, SIGHASH_ALL)
            # TODO: figure out how to better protect privkey
            privkey = bitcoind.dumpprivkey(redeemPubKey)
            sig = privkey.sign(sighash) + bytes([SIGHASH_ALL])
            print("SECRET", secret)
            preimage = b(secret)
            txin.scriptSig = CScript([sig, privkey.pub, preimage, OP_TRUE, zec_redeemScript])

            print("txin.scriptSig", b2x(txin.scriptSig))
            txin_scriptPubKey = zec_redeemScript.to_p2sh_scriptPubKey()
            print('Redeem txhex', b2x(tx.serialize()))
            VerifyScript(txin.scriptSig, txin_scriptPubKey, tx, 0, (SCRIPT_VERIFY_P2SH,))
            print("script verified, sending raw tx")
            txid = bitcoind.sendrawtransaction(tx)
            print("Txid of submitted redeem tx: ", b2x(lx(b2x(txid))))
            print("TXID SUCCESSFULLY REDEEMED")
            return 'redeem_tx', b2x(lx(b2x(txid)))
        else:
            print("nLocktime exceeded, refunding")
            refundPubKey = find_refundAddr(contract)
            print('refundPubKey', refundPubKey)
            txid = bitcoind.sendtoaddress(refundPubKey, fundtx['amount'] - FEE)
            print("Txid of refund tx:",  b2x(lx(b2x(txid))))
            print("TXID SUCCESSFULLY REFUNDED")
            return 'refund_tx', b2x(lx(b2x(txid)))
    else:
        print("No contract for this p2sh found in database", p2sh)

def find_redeemblocknum(contract):
    scriptarray = parse_script(contract.redeemScript)
    redeemblocknum = scriptarray[8]
    return int(redeemblocknum)

def find_redeemAddr(contract):
    scriptarray = parse_script(contract.redeemScript)
    redeemer = scriptarray[6]
    redeemAddr = P2PKHBitcoinAddress.from_bytes(x(redeemer))
    return redeemAddr

def find_refundAddr(contract):
    scriptarray = parse_script(contract.redeemScript)
    funder = scriptarray[13]
    refundAddr = P2PKHBitcoinAddress.from_bytes(x(funder))
    return refundAddr

# def find_recipient(contract):
    # initiator = CBitcoinAddress(contract.initiator)
    # fulfiller = CBitcoinAddress(contract.fulfiller)
    # print("Initiator", b2x(initiator))
    # print("Fulfiler", b2x(fulfiller))
    # make this dependent on actual fund tx to p2sh, not contract
    # print("Contract fund_tx", contract.fund_tx)
    # txid = contract.fund_tx
    # raw = bitcoind.gettransaction(lx(txid))['hex']
    # print("Raw tx", raw)
    # # print("Raw", raw)
    # decoded = zcashd.decoderawtransaction(raw + '00')
    # scriptSig = decoded['vin'][0]['scriptSig']
    # print("Decoded", scriptSig)
    # asm = scriptSig['asm'].split(" ")
    # pubkey = asm[1]
    # print('pubkey', pubkey)
    # redeemPubkey = P2PKHBitcoinAddress.from_pubkey(x(pubkey))
    # print('redeemPubkey', redeemPubkey)

def find_transaction_to_address(p2sh):
    bitcoind.importaddress(p2sh, "", False)
    txs = bitcoind.listunspent()
    for tx in txs:
        if tx['address'] == CBitcoinAddress(p2sh):
            print("Found tx to p2sh", p2sh)
            print(tx)
            return tx

def new_bitcoin_addr():
    addr = bitcoind.getnewaddress()
    print('new btc addr', addr.to_scriptPubKey)
    return addr.to_scriptPubKey()

def generate(num):
    blocks = bitcoind.generate(num)
    return blocks