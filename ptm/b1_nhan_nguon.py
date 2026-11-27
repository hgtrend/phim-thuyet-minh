"""B1 — NHẬN VIDEO GỐC vào <tập>/01_raw/goc.mp4.

    python -m ptm.b1_nhan_nguon --tap T01_ten_bo --ket-qua lay_link.json   # kết quả món HG Trend «Lấy link tải video Douyin, Bilibili» (trợ lý lưu ra tệp)
    python -m ptm.b1_nhan_nguon --tap T01_ten_bo --tep video_da_tai.mp4     # video đã có trên máy
    python -m ptm.b1_nhan_nguon --tap T01_ten_bo --yt-dlp <link Bilibili>   # Bilibili bằng yt-dlp (nếu đã cài), có khi nét hơn 480p

- Douyin: một tệp mp4. Bilibili: hình + tiếng hai tệp, tải kèm Referer rồi ghép. Link hết hạn sau vài giờ — hết hạn thì chạy lại món HG Trend.
- Mã hoá không phải H.264 (vd H.265 / bytevc1) ⇒ đổi sang H.264 (bước làm mờ đọc khung hình cần H.264).
- Ghi tác giả vào tap.json («tac_gia») để bước xin phép tác giả dùng.
- Rào dò trùng: chưa chạy B0 hoặc B0 ra ĐỎ thì dừng (trừ khi --ep).
"""
import argparse, json, shutil, subprocess, sys
from pathlib import Path

from .chung import can, chay, doc_tap, ffprobe_video, ghi_json, ghi_tap, la_link_web, log, mo_web, tap_dir, xong_buoc

UA = 'Mozilla/5.0 (compatible; phim-thuyet-minh/1.0)'
REFERER = {'Douyin': 'https://www.douyin.com/', 'Bilibili': 'https://www.bilibili.com/'}


def tai(url, ra, referer, tran=2 * 1024 ** 3):
    """Tải một link về tệp (qua tệp .part, xong mới đổi tên), kèm Referer (Bilibili thiếu Referer ⇒ 403). Trả True nếu được."""
    if not la_link_web(url):                                  # chỉ http(s): link file://… trong tệp kết quả không được đọc tệp trên máy
        log(f'⚠️ bỏ link không phải http(s): {str(url)[:80]}')
        return False
    ra, tam = Path(ra), Path(str(ra) + '.part')
    try:
        with mo_web(url, {'User-Agent': UA, 'Referer': referer}, 60) as r, open(tam, 'wb') as f:   # chuyển hướng sang file:// … bị chặn
            n = 0
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                n += len(b)
                if n > tran:
                    raise ValueError('tệp quá lớn')
                f.write(b)
        if tam.stat().st_size <= 50_000:
            raise ValueError('tệp quá nhỏ')
        tam.replace(ra)
        return True
    except Exception as e:                                   # link hỏng / hết hạn / tải đứt ⇒ bỏ tệp dở, thử link dự phòng
        tam.unlink(missing_ok=True)
        log(f'⚠️ tải hỏng ({type(e).__name__}: {str(e)[:120]}) — thử link dự phòng')
        return False


def tai_mot_trong(ds, ra, referer):
    if isinstance(ds, str):                                   # một link trần thay vì danh sách
        ds = [ds]
    for u in ds if isinstance(ds, list) else []:
        if tai(u, ra, referer):
            return True
    return False


def tu_ket_qua(f, raw):
    """Đọc kết quả món HG Trend (cả gói trả về hoặc chỉ phần ket_qua) → tải về goc.mp4. Trả (thông tin video, tác giả)."""
    if not Path(f).is_file():
        sys.exit(f'🔴 Không thấy tệp kết quả {f}')
    try:
        d = json.loads(Path(f).read_text(encoding='utf-8'))
    except ValueError:
        sys.exit(f'🔴 {f} không phải JSON — lưu NGUYÊN kết quả món «Lấy link tải video» vào tệp.')
    d = (d.get('ket_qua') or d) if isinstance(d, dict) else {}
    d = d if isinstance(d, dict) else {}
    if d.get('loi') or not d.get('link_tai'):
        sys.exit(f"🔴 Tệp kết quả không có link tải ({d.get('loi') or 'thiếu link_tai'}). Chạy lại món «Lấy link tải video» rồi lưu kết quả.")
    v, lt = d.get('video') if isinstance(d.get('video'), dict) else {}, d['link_tai']
    nen = v.get('nen_tang') or ('Bilibili' if isinstance(lt, dict) else 'Douyin')
    ref = REFERER.get(nen, 'https://www.douyin.com/')
    if isinstance(lt, dict):                                  # Bilibili: hình + tiếng riêng
        if not tai_mot_trong(lt.get('hinh') or [], raw / 'hinh.m4s', ref) or not tai_mot_trong(lt.get('tieng') or [], raw / 'tieng.m4s', ref):
            sys.exit('🔴 Tải Bilibili hỏng (link hết hạn?). Chạy lại món «Lấy link tải video» rồi thử lại.')
        chay([can('ffmpeg'), '-hide_banner', '-v', 'error', '-y', '-i', raw / 'hinh.m4s', '-i', raw / 'tieng.m4s', '-c', 'copy', raw / 'goc_tam.mp4'])
        (raw / 'hinh.m4s').unlink()
        (raw / 'tieng.m4s').unlink()
    else:
        if not tai_mot_trong(lt, raw / 'goc_tam.mp4', ref):
            sys.exit('🔴 Tải Douyin hỏng cả các link (hết hạn?). Chạy lại món «Lấy link tải video» rồi thử lại.')
    ffprobe_video(raw / 'goc_tam.mp4')                        # là video thật (không phải trang lỗi) mới thay bản cũ
    (raw / 'goc_tam.mp4').replace(raw / 'goc.mp4')
    return v, d.get('tac_gia') if isinstance(d.get('tac_gia'), dict) else {}


def doi_h264(raw):
    info = ffprobe_video(raw / 'goc.mp4')
    if info.get('codec') == 'h264' and not info.get('xoay'):
        return info
    log(f"mã hoá {info.get('codec')}{' · có thẻ xoay ' + str(info.get('xoay')) + '°' if info.get('xoay') else ''} ⇒ mã hoá lại H.264 "
        "(bước làm mờ cần đọc từng khung; thẻ xoay làm lệch khung khi đọc chữ — mã hoá lại thì ffmpeg xoay hẳn hình)")
    tam = raw / 'goc_h264.mp4'
    hinh = ['-c:v', 'libx264', '-crf', '16', '-preset', 'medium', '-pix_fmt', 'yuv420p']
    try:                                                      # giữ nguyên tiếng gốc (bước tách tiếng cần bản ít nén nhất); không được thì mới nén AAC
        chay([can('ffmpeg'), '-hide_banner', '-v', 'error', '-y', '-i', raw / 'goc.mp4', *hinh, '-c:a', 'copy', tam])
    except Exception:
        chay([can('ffmpeg'), '-hide_banner', '-v', 'error', '-y', '-i', raw / 'goc.mp4', *hinh, '-c:a', 'aac', '-b:a', '192k', tam])
    tam.replace(raw / 'goc.mp4')
    return ffprobe_video(raw / 'goc.mp4')


def main(argv=None):
    ap = argparse.ArgumentParser(description='B1 — nhận video gốc')
    ap.add_argument('--tap', required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--ket-qua', help='tệp JSON kết quả món «Lấy link tải video Douyin, Bilibili» của HG Trend')
    g.add_argument('--tep', help='video đã có trên máy')
    g.add_argument('--yt-dlp', dest='ytdlp', help='link Bilibili tải bằng yt-dlp')
    ap.add_argument('--ep', action='store_true', help='bỏ qua rào dò trùng B0')
    ap.add_argument('--ghi-de', action='store_true', help='đã có 01_raw/goc.mp4 thì xoá và nhận lại')
    a = ap.parse_args(argv)
    t = doc_tap(a.tap)
    muc = t.get('do_trung')
    if not a.ep:
        if muc is None:
            sys.exit('🔴 DỪNG: chưa dò trùng tập này (python -m ptm.b0_do_trung). Muốn bỏ rào: --ep')
        if muc == 'do':
            sys.exit('🔴 DỪNG: dò trùng ra ĐỎ (đã có bản tiếng Việt trên YouTube). Muốn bỏ rào: --ep')
        if muc == 'vang':
            log('🟡 Dò trùng ra VÀNG — vẫn nhận, nhưng phải tự xem các video nghi trùng trước khi đăng')
    raw = tap_dir(a.tap) / '01_raw'
    raw.mkdir(exist_ok=True)
    for x in [*raw.glob('goc_tam.mp4'), *raw.glob('goc_h264.mp4'), *raw.glob('_ytdlp*'), *raw.glob('*.part'), *raw.glob('*.m4s')]:   # đồ dở lượt trước
        x.unlink(missing_ok=True)
    v, tg = {}, {}
    if (raw / 'goc.mp4').exists() and not a.ghi_de:          # chạy lại: không tải lại, chỉ ghi lại thông tin (muốn thay: --ghi-de)
        log('đã có 01_raw/goc.mp4 — không nhận lại (muốn thay: --ghi-de)')
        if a.ket_qua:
            try:
                d = json.loads(Path(a.ket_qua).read_text(encoding='utf-8'))
                d = (d.get('ket_qua') or d) if isinstance(d, dict) else {}
                v = d.get('video') if isinstance(d.get('video'), dict) else {}
                tg = d.get('tac_gia') if isinstance(d.get('tac_gia'), dict) else {}
            except (OSError, ValueError, AttributeError):
                pass
    elif a.tep:
        if not Path(a.tep).is_file():
            sys.exit(f'🔴 Không thấy tệp {a.tep}')
        if Path(a.tep).resolve() != (raw / 'goc.mp4').resolve():
            shutil.copy2(a.tep, raw / 'goc_tam.mp4')          # chép + kiểm là video xong mới thay bản cũ
            ffprobe_video(raw / 'goc_tam.mp4')
            (raw / 'goc_tam.mp4').replace(raw / 'goc.mp4')
    elif a.ket_qua:
        v, tg = tu_ket_qua(a.ket_qua, raw)                    # tải qua .part, thành công mới thay goc.mp4 cũ
    else:
        if not la_link_web(a.ytdlp):                          # chặn chuỗi bắt đầu bằng «-» bị yt-dlp hiểu thành tham số
            sys.exit('🔴 --yt-dlp cần một link http(s)')
        yt = shutil.which('yt-dlp')
        if not yt:
            sys.exit('🔴 Chưa cài yt-dlp («pip install yt-dlp»). Hoặc dùng món HG Trend rồi --ket-qua.')
        chay([yt, '--socket-timeout', '30', '-f', 'bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b', '--merge-output-format', 'mp4',
              '--no-playlist', '-o', str(raw / '_ytdlp.%(ext)s'), '--', a.ytdlp], stdin=subprocess.DEVNULL)
        mp4 = sorted(raw.glob('_ytdlp*.mp4'), key=lambda p: p.stat().st_size, reverse=True)   # tải ra tên tạm, xong mới thay goc.mp4
        if not mp4:
            sys.exit('🔴 yt-dlp không ra tệp mp4 nào')
        ffprobe_video(mp4[0])                                   # là video thật mới thay bản cũ
        mp4[0].replace(raw / 'goc.mp4')
        for x in raw.glob('_ytdlp*'):
            x.unlink(missing_ok=True)
        v = {'nen_tang': 'Bilibili', 'link': a.ytdlp}
    info = doi_h264(raw)
    log(f"goc.mp4: {info['w']}x{info['h']} {info['fps']}fps {info['dur']:.1f}s")
    them = {'video': info}
    if v:
        them['nguon'] = {k: v.get(k) for k in ('nen_tang', 'link', 'tieu_de', 'thoi_luong_giay', 'dang_ngay', 'phan') if v.get(k) is not None}
    if tg:
        them['tac_gia'] = tg
        x = t.get('xin_phep') or {}
        them['xin_phep'] = {'trang_thai': x.get('trang_thai') or 'chua_gui', **{k: x[k] for k in x if k != 'trang_thai'}}
    ghi_tap(a.tap, **them)
    if v or tg or not (raw / 'nguon.json').exists():         # chạy lại không có thông tin mới ⇒ giữ nguon.json cũ (tác giả)
        ghi_json(raw / 'nguon.json', {'video': v, 'tac_gia': tg})
    xong_buoc(a.tap, 'b1_nhan_nguon', **info)
    if tg and (them['xin_phep']['trang_thai'] == 'chua_gui'):
        log('🟡 Nhớ xin phép tác giả trước khi đăng: python -m ptm.xin_phep --tap ' + a.tap)


if __name__ == '__main__':
    main()
