import os
from FATtools.Volume import openvolume
from FATtools import disk
import sys
import hmac
import hashlib
from Crypto.Cipher import AES
import io
import struct
import binascii

bindKey = binascii.unhexlify(b"901a84fb13a744a378c5018a60f58c22")


def recursive_copy(img, d):
    for root, dirs, files in img.opendir(d).walk():
        for name in dirs:
            fullpath = os.path.join(root, name).replace("\\", "/")[2:]
            os.makedirs(fullpath, exist_ok=True)
        for name in files:
            fullpath = os.path.join(root, name).replace("\\", "/")[2:]
            print("Extracting: "+ fullpath +" ...")
            
            if not os.path.exists(fullpath):
                inf = img.open(fullpath)
                ouf = open(fullpath, "wb")
                
                buf = inf.read()
                ouf.write(buf)
                    
                ouf.close()
                inf.close()

def get_title_id(img):
    return img.opendir("app").listdir()[0]

def get_rif(img):
    for root, dirs, files in img.opendir("license").walk():
        for name in files:
            fullpath = os.path.join(root, name).replace("\\", "/")[2:]
            f = img.open(fullpath)
            rif = f.read()
            f.close()
            return rif


def get_rif_keys(path):
    v = open(path, "rb")
    header = v.read(0x200)
    if header[:0x4] == b"VCI\x00":
        vciheader = struct.unpack("3sxIQ32s32s432x", header)
        key1 = vciheader[3]
        key2 = vciheader[4]
        rifKey = derive_rif_key(key1, key2)
        return rifKey
    elif header[:0x4] == b"PSV\x00":
        psvheader = struct.unpack("3sxII32s20s32sQQ400x", header)
        rifKey = psvheader[3]
        return rifKey
    else:
        print("Error: invalid magic number")
        quit()
    
def get_gro0(path):
    fd = disk.disk(path)
    
    fd.seek(0x00, os.SEEK_SET)
    header = fd.read(0x200)
    mbr = fd.read(0x50)
    
    if header[:0x4] == b"VCI\x00":
        deviceOffset = 1;
    if header[:0x4] == b"PSV\x00":
        psvheader = struct.unpack("3sxII32s20s32sQQ400x", header)
        startSector = psvheader[7]
        deviceOffset = startSector
    
    
    for i in range(0, 0x10):
        partition = struct.unpack("IIBBBIH", fd.read(0x11) + b"\x00")
        off = partition[0]
        sz = partition[1]
        cde = partition[2]
        typ = partition[3]
        acti = partition[4]
        flgs = partition[5]
        unk = partition[6]
        
        if cde == 0x9: # gro0
            part = disk.partition(fd, (off + deviceOffset) * 0x200, sz * 0x200)
            part.mbr = None
            disk.partition.open = openvolume
            return part

def decrypt_bind_data(rifKey, bindData):
    bindHmac = hmac.new(bindKey, bindData, hashlib.sha256).digest()
    cipher = AES.new(bindHmac[:0x10], AES.MODE_CBC, bindHmac[0x10:0x20])
    return cipher.decrypt(rifKey)
    
def decrypt_klicensee(rif, rifKey):
    bindData = rifKey + rif[:0x70]
    key2 = rif[0xA0:0xA0+0x10]
    
    return decrypt_bind_data(key2, bindData)    
    
def derive_rif_key(key1, key2):
    m = hashlib.sha256()
    m.update(key1)
    m.update(key2)
    return m.digest()

def swap16(i):
    return struct.unpack("<H", struct.pack(">H", i))[0]
    
def swap32(i):
    return struct.unpack("<I", struct.pack(">I", i))[0]
    
def create_nonpdrm_rif(rif, klicensee):
    rifHeader = struct.unpack("HHHHQ48s16s16sQQ40sQ16s16s16s16s20sIII256s", rif)
    
    flags = rifHeader[4]
    
    contentId = rifHeader[5]
    flags2 = rifHeader[11]
    skuFlag = rifHeader[19]

    # modify license flags
    flags = swap16(flags) & 0b01111111111
    
    if swap32(skuFlag) == 1 or swap32(skuFlag) == 3:
        skuFlag = swap32(3)
    else:
        skuFlag = swap32(0)
    
    nonpdrmRif = struct.pack("HHHHQ48s16x16s56xQ92xI256x", swap16(1), swap16(1), swap16(1), swap16(flags), 0x0123456789ABCDEF, contentId, klicensee, flags2, skuFlag)
    
    return nonpdrmRif

def create_nonpdrm_dump(image, rifKey):
    gro0Part = get_gro0(image)
    img = openvolume(gro0Part)

    titleId = get_title_id(img)
    recursive_copy(img, "app")

    rif = get_rif(img)
    klicensee = decrypt_klicensee(rif, rifKey)
    nonpdrmRif = create_nonpdrm_rif(rif, klicensee)

    print("Creating: work.bin ...")
    open("app/"+titleId+"/sce_sys/package/work.bin", "wb").write(nonpdrmRif)

    img.close()


def gc2nonpdrm(vciFile):
    rifKey = get_rif_keys(vciFile)
    create_nonpdrm_dump(vciFile, rifKey)



if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: <vcifile or psvfile>")
        sys.exit()
    gcFile = sys.argv[1]
    
    gc2nonpdrm(gcFile)