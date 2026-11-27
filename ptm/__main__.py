"""Lệnh chung:  python -m ptm <bước> --tap <tên tập> [tham số của bước]   ·   python -m ptm trang-thai --tap <tên tập>

Bước theo thứ tự:  do-trung · nhan · tach-tieng · nghe · giong · mo-chu · nhac · dung · bia · kiem   (+ xin-phep bất kỳ lúc nào)
Mã thoát 3 = bước đã ghi PHIẾU (CAN_*.json) chờ trợ lý làm — làm xong chạy lại đúng bước đó.
"""
import importlib, json, sys

from .chung import BUOC, doc_tap, goc_du_an

LENH = {'do-trung': 'b0_do_trung', 'nhan': 'b1_nhan_nguon', 'tach-tieng': 'b2_tach_tieng', 'nghe': 'b3_nghe', 'giong': 'b4_giong',
        'mo-chu': 'b5_mo_chu', 'nhac': 'b6_nhac', 'dung': 'b7_dung', 'bia': 'b8_bia', 'kiem': 'kiem', 'xin-phep': 'xin_phep'}


def trang_thai(argv):
    if '--tap' not in argv or argv.index('--tap') + 1 >= len(argv):
        sys.exit('cần --tap <tên tập>')
    slug = argv[argv.index('--tap') + 1]
    t = doc_tap(slug)
    d = goc_du_an() / slug
    print(f'Tập {slug} · thư mục {d}')
    xong = t.get('buoc') or {}
    for b in BUOC:
        print(f"  {'✓' if b in xong else '·'} {b}" + (f"  ({xong[b].get('luc')})" if b in xong else ''))
    xp = (t.get('xin_phep') or {}).get('trang_thai')
    print(f"  xin phép tác giả: {xp or 'chưa soạn thư'}")
    phieu = sorted(d.glob('*/CAN_*.json'))
    for p in phieu:
        try:
            v = json.loads(p.read_text(encoding='utf-8')).get('viec')
        except ValueError:
            v = '?'
        print(f'  ⏸ phiếu chờ trợ lý: {p.relative_to(d)} — {v}')


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help'):
        print(__doc__)
        return
    lenh, argv = sys.argv[1], sys.argv[2:]
    if lenh == 'trang-thai':
        return trang_thai(argv)
    if lenh not in LENH:
        sys.exit(f'Không có lệnh «{lenh}». Các lệnh: ' + ', '.join(list(LENH) + ['trang-thai']))
    importlib.import_module('.' + LENH[lenh], 'ptm').main(argv)


if __name__ == '__main__':
    main()
