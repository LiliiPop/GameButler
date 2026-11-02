"""生成 GameButler.res（图标 + 管理员权限清单 + 版本信息），给 mcs -win32res 用。
Mono 的 mcs 不会嵌入 -win32manifest，所以自己拼 .res。"""
import struct, sys

def entry(rtype, rid, data, flags=0x1030, lang=0):
    hdr = struct.pack('<IIHHHHIHHII', len(data), 32, 0xFFFF, rtype, 0xFFFF, rid, 0, flags, lang, 0, 0)
    pad = (-len(data)) % 4
    return hdr + data + b'\0' * pad

def ver_block(key, value=b'', vtype=1, children=b'', wlen=None):
    k = key.encode('utf-16-le') + b'\0\0'
    head_len = 6 + len(k)
    pad1 = (-head_len) % 4
    body = value + b'\0' * ((-len(value)) % 4) + children if value else children
    total = head_len + pad1 + body.__len__()
    vl = wlen if wlen is not None else (len(value) // 2 if vtype == 1 else len(value))
    return struct.pack('<HHH', total, vl, vtype) + k + b'\0' * pad1 + body

def string(key, val):
    v = val.encode('utf-16-le') + b'\0\0'
    blk = ver_block(key, v, 1, wlen=len(v) // 2)
    return blk + b'\0' * ((-len(blk)) % 4)

def version_res(ver=(1, 0, 0, 0)):
    ms, ls = (ver[0] << 16) | ver[1], (ver[2] << 16) | ver[3]
    ffi = struct.pack('<13I', 0xFEEF04BD, 0x00010000, ms, ls, ms, ls, 0x3F, 0, 0x40004, 1, 0, 0, 0)
    strs = b''.join(string(k, v) for k, v in [
        ('CompanyName', ''), ('FileDescription', '游戏日常管家'), ('FileVersion', '%d.%d.%d.%d' % ver),
        ('InternalName', 'GameButler'), ('OriginalFilename', 'GameButler.exe'), ('ProductName', '游戏日常管家'),
        ('ProductVersion', '%d.%d.%d.%d' % ver)])
    table = ver_block('080404b0', children=strs, vtype=1, wlen=0)
    sfi = ver_block('StringFileInfo', children=table + b'\0' * ((-len(table)) % 4), vtype=1, wlen=0)
    var = ver_block('Translation', struct.pack('<HH', 0x0804, 0x04B0), 0)
    vfi = ver_block('VarFileInfo', children=var, vtype=1, wlen=0)
    root = ver_block('VS_VERSION_INFO', ffi, 0, children=sfi + b'\0' * ((-len(sfi)) % 4) + vfi)
    return root

def main(ico, manifest, out):
    data = open(ico, 'rb').read()
    _, _, n = struct.unpack('<HHH', data[:6])
    res = struct.pack('<IIHHHHIHHII', 0, 32, 0xFFFF, 0, 0xFFFF, 0, 0, 0, 0, 0, 0)
    grp = struct.pack('<HHH', 0, 1, n)
    for i in range(n):
        w, h, c, r, planes, bits, size, off = struct.unpack('<BBBBHHII', data[6 + 16 * i: 22 + 16 * i])
        res += entry(3, i + 1, data[off:off + size])
        grp += struct.pack('<BBBBHHIH', w, h, c, r, planes, bits, size, i + 1)
    res += entry(14, 32512, grp)
    res += entry(24, 1, open(manifest, 'rb').read(), flags=0x0030, lang=0)
    res += entry(16, 1, version_res(), flags=0x0030, lang=0x0804)
    open(out, 'wb').write(res)

if __name__ == '__main__':
    main(*sys.argv[1:4])
