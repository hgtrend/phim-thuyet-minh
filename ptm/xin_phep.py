"""XIN PHÉP TÁC GIẢ — soạn thư xin quyền dịch, lồng tiếng, đăng lại; ghi trạng thái vào tap.json («xin_phep»). CHỈ NHẮC, KHÔNG CHẶN đăng.

    python -m ptm.xin_phep --tap T01 --kenh "Tên kênh của bạn" --ten-ban "Tên bạn"   # soạn thư → 00_xin_phep/THU.md
    python -m ptm.xin_phep --tap T01 --trang-thai da_gui --ghi-chu "nhắn tin Douyin 26/11"
    python -m ptm.xin_phep --tap T01 --trang-thai dong_y --bang-chung anh_tra_loi.png  # cất ảnh / thư trả lời làm bằng chứng
    python -m ptm.xin_phep --tap T01 --xem

Trạng thái: chua_gui · da_gui · dong_y · tu_choi · khong_lien_he_duoc. Tác giả lấy từ bước B1 (món «Lấy link tải video» trả tên, link kênh,
giới thiệu kênh). Gửi thư là việc của BẠN (nhắn tin trên Douyin / Bilibili, hoặc email nếu tác giả ghi) — máy không tự gửi.
"""
import argparse, re, shutil, sys, time
from pathlib import Path

from .chung import doc_tap, ghi_tap, log, tap_dir

TRANG_THAI = ('chua_gui', 'da_gui', 'dong_y', 'tu_choi', 'khong_lien_he_duoc')
THU_ZH = """您好，{ten}！

我是一名越南的视频创作者，在 YouTube 上运营频道「{kenh}」。我非常喜欢您的作品《{tieu_de}》：
{link}

我想向您申请授权：把这部作品翻译成越南语，配上越南语解说和字幕，发布在我的 YouTube 频道上，让越南观众也能欣赏您的作品。

我会在视频简介中注明原作者「{ten}」和原视频链接，不会说是我自己的作品。如果您希望分享收益、指定署名方式，或者有其他条件，请告诉我。

如果您同意，回复「同意」就可以；如果您不同意，我就不会发布。

谢谢您！
{ten_ban}
"""
THU_VI = """Chào {ten}!

Tôi là người làm video ở Việt Nam, có kênh YouTube «{kenh}». Tôi rất thích tác phẩm «{tieu_de}» của bạn:
{link}

Tôi xin phép bạn cho tôi dịch tác phẩm này sang tiếng Việt, lồng tiếng thuyết minh và phụ đề tiếng Việt, rồi đăng lên kênh YouTube của tôi để người
xem Việt Nam cũng được xem tác phẩm của bạn.

Tôi sẽ ghi rõ tác giả «{ten}» và link video gốc trong phần mô tả, không nhận là tác phẩm của mình. Nếu bạn muốn chia doanh thu, muốn ghi tên theo
cách riêng, hay có điều kiện khác, xin cho tôi biết.

Nếu đồng ý, bạn chỉ cần trả lời «同意» (đồng ý); nếu không đồng ý, tôi sẽ không đăng.

Cảm ơn bạn!
{ten_ban}
"""


def cach_lien_he(tg):
    """Gợi ý chỗ liên hệ từ link kênh + phần giới thiệu kênh (email, WeChat, QQ, «商务合作»)."""
    ra = []
    if tg.get('link_kenh'):
        ra.append(f"Nhắn tin riêng trên kênh: {tg['link_kenh']} (Douyin: nút «私信»; Bilibili: «发消息»)")
    gt = ' '.join(str(tg.get(k) or '') for k in ('gioi_thieu_kenh', 'mo_ta_video'))
    for e in sorted(set(re.findall(r'[\w.+-]+@[\w-]+\.[\w.]+', gt))):
        ra.append(f'Email ghi trong giới thiệu: {e}')
    for nhan, rx in (('WeChat', r'(?:微信|vx|VX|wx|WX|weixin)[：:\s]*([A-Za-z][\w-]{5,19})'), ('QQ', r'(?:QQ|qq)[：:\s]*(\d{5,11})')):
        for m in sorted(set(re.findall(rx, gt))):
            ra.append(f'{nhan} ghi trong giới thiệu: {m}')
    if re.search(r'商务|合作|商单|business', gt, re.I):
        ra.append('Giới thiệu kênh có nhắc «hợp tác / thương mại» (商务合作) — nên dùng đúng kênh liên hệ đó.')
    return ra


def main(argv=None):
    ap = argparse.ArgumentParser(description='Xin phép tác giả (chỉ nhắc, không chặn)')
    ap.add_argument('--tap', required=True)
    ap.add_argument('--kenh', help='tên kênh YouTube của bạn (để điền thư)')
    ap.add_argument('--ten-ban', help='tên bạn ký cuối thư')
    ap.add_argument('--trang-thai', choices=TRANG_THAI)
    ap.add_argument('--ghi-chu')
    ap.add_argument('--bang-chung', help='ảnh chụp / tệp thư trả lời của tác giả')
    ap.add_argument('--xem', action='store_true')
    a = ap.parse_args(argv)
    t = doc_tap(a.tap)
    tg, ng = t.get('tac_gia') or {}, t.get('nguon') or {}
    xp = dict(t.get('xin_phep') or {'trang_thai': 'chua_gui'})
    d = tap_dir(a.tap) / '00_xin_phep'
    if a.xem:
        print(f"Tác giả: {tg.get('ten') or '(chưa biết — chạy B1 bằng kết quả món HG Trend)'} · trạng thái: {xp.get('trang_thai')}"
              + (f" · {xp.get('ghi_chu')}" if xp.get('ghi_chu') else ''))
        return
    if a.trang_thai:
        xp['trang_thai'] = a.trang_thai
        xp.setdefault('lich_su', []).append({'luc': time.strftime('%Y-%m-%d %H:%M'), 'trang_thai': a.trang_thai, 'ghi_chu': a.ghi_chu or ''})
        if a.ghi_chu:
            xp['ghi_chu'] = a.ghi_chu
        if a.bang_chung:
            if not Path(a.bang_chung).is_file():
                sys.exit(f'🔴 Không thấy tệp bằng chứng {a.bang_chung}')
            d.mkdir(parents=True, exist_ok=True)
            dich = d / ('bang_chung_' + time.strftime('%y%m%d_%H%M') + '_' + re.sub(r'[^\w.\-]', '_', a.bang_chung.rsplit('/', 1)[-1]))
            shutil.copy2(a.bang_chung, dich)
            xp.setdefault('bang_chung', []).append(str(dich.relative_to(tap_dir(a.tap))))
        ghi_tap(a.tap, xin_phep=xp)
        log(f"ghi trạng thái xin phép: {a.trang_thai}" + ('' if a.trang_thai == 'dong_y' else ' — chưa có đồng ý: nhắc lại trước khi đăng (không chặn)'))
        return
    if not tg.get('ten'):
        log('🟡 Chưa biết tác giả (video nhận bằng --tep). Điền tay tên + link kênh vào tap.json «tac_gia», hoặc dùng món HG Trend ở B1.')
    o = {'ten': tg.get('ten') or '作者', 'kenh': a.kenh or '<tên kênh của bạn>', 'ten_ban': a.ten_ban or '<tên bạn>',
         'tieu_de': (ng.get('tieu_de') or '').split('#')[0].strip()[:60] or '<tên tác phẩm>', 'link': ng.get('link') or '<link video gốc>'}
    d.mkdir(parents=True, exist_ok=True)
    lh = cach_lien_he(tg)
    chu = ('# Thư xin phép tác giả\n\n'
           '> Gửi bản **tiếng Trung** cho tác giả. Bản tiếng Việt chỉ để bạn hiểu mình đang viết gì. Đọc lại, sửa chỗ <…> trước khi gửi.\n'
           '> Chưa được đồng ý mà vẫn đăng là rủi ro của bạn (kênh có thể bị báo vi phạm bản quyền). Máy chỉ nhắc, không chặn.\n\n'
           '## Gửi ở đâu\n\n' + ('\n'.join(f'- {x}' for x in lh) if lh else '- Không thấy cách liên hệ — mở kênh tác giả xem phần giới thiệu.') + '\n\n'
           '## Bản tiếng Trung (gửi bản này)\n\n```\n' + THU_ZH.format(**o) + '```\n\n## Bản tiếng Việt (để hiểu)\n\n```\n' + THU_VI.format(**o) + '```\n\n'
           f'## Ghi lại sau khi gửi\n\n```\npython -m ptm.xin_phep --tap {a.tap} --trang-thai da_gui --ghi-chu "gửi qua …"\n'
           f'python -m ptm.xin_phep --tap {a.tap} --trang-thai dong_y --bang-chung <ảnh chụp trả lời>\n```\n')
    (d / 'THU.md').write_text(chu, encoding='utf-8')
    xp.setdefault('trang_thai', 'chua_gui')
    xp['thu'] = '00_xin_phep/THU.md'
    ghi_tap(a.tap, xin_phep=xp)
    log(f'đã soạn thư: {d / "THU.md"} · {len(lh)} cách liên hệ gợi ý · trạng thái {xp["trang_thai"]}')


if __name__ == '__main__':
    main()
