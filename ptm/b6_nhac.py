"""B6 — NHẠC NỀN ĐÚNG CHỖ: dò chỗ nào nguồn có nhạc, đặt nhạc mới (không lời) vào đúng chỗ đó.

1. Đo năng lượng `02_tieng/nhac_goc.wav` (đã bỏ giọng) theo 0,5 s → các khoảng nguồn CÓ nhạc (gộp kẽ < 2 s, bỏ khoảng < 4 s).
   Trống mạnh → «hanh_dong», vừa → «hoi_hop», còn lại «cam_xuc» (đoán thô — sửa trong nhac_cue.json rồi chạy --giu-cue).
2. Khoảng dài > 75 s chia thành cảnh 25–75 s (cắt ở mốc nối tập nếu có, rồi chia đều), giữ tâm trạng.
   Mốc nối tập: tap.json «cac_tap» = [{"bat_dau": giây}, …] — KHÔNG bước nào của ptm tự ghi; video ghép nhiều tập thì người dùng / trợ lý
   tự thêm (không có thì chỉ chia đều).
3. Mỗi khoảng lấy một bài trong `06_nhac/kho/<tâm trạng>_*.mp3|wav` (xoay vòng, tránh lặp bài liền kề). Thiếu bài cho tâm trạng nào
   ⇒ phiếu `06_nhac/CAN_NHAC.json` (trợ lý làm bằng món HG Trend «Làm nhạc nền không lời», hoặc người dùng tự bỏ bài vào kho), thoát mã 3.
4. Ghép `06_nhac/nhac_bed.wav` (vào 1 s / ra 1,5 s, bài ngắn thì lặp). B7 nén nhạc dưới giọng.

    python -m ptm.b6_nhac --tap <slug> [--giu-cue] [--mot-bai <tệp>] [--khong-nhac] [--dung-bai-co-san]
"""
import argparse, json, math, sys, time
from pathlib import Path

from .chung import can, chay, cho_tro_ly, doc_tap, ffprobe_dur, ghi_json, log, tap_dir, xong_buoc

MO_TA_MOOD = {
    "hanh_dong": "fast intense battle music, driving percussion, brass stabs, rising tension, 140 BPM, epic anime fight",
    "hoi_hop": "tense suspenseful underscore, low pulsing synth, ticking rhythm, sparse strings, 100 BPM, danger approaching",
    "cam_xuc": "soft emotional piano and strings, gentle, warm, slow 70 BPM, bittersweet anime drama moment",
    "vui": "light playful upbeat tune, pizzicato strings, marimba, cheerful 120 BPM, comedic anime slice of life",
    "de_thuong": "cute whimsical tune, plucked strings and celesta, light bamboo flute, bouncy 105 BPM, adorable mischievous character",
    "bi_an": "mysterious eerie underscore, sustained low drone, soft bells, distant solo melody, slow 65 BPM, ghostly secret being revealed",
}
DUOI = ("mp3", "wav", "m4a", "ogg", "flac")
CANH_MIN, CANH_MAX = 25.0, 75.0


def do_khoang_nhac(nhac_goc, drums):
    import librosa, numpy as np
    y, sr = librosa.load(str(nhac_goc), sr=22050, mono=True)
    hop = int(sr * 0.5)
    rms = librosa.feature.rms(y=y, frame_length=hop * 2, hop_length=hop)[0]
    db = 20 * np.log10(rms + 1e-8)
    dinh = np.percentile(db, 95)
    san = float(max(-48.0, dinh - 25.0))     # có nhạc = trên sàn này (nhạc liên tục thường −30…−22 dB)
    co = (db > san)
    if Path(drums).exists():
        yd, _ = librosa.load(str(drums), sr=22050, mono=True)
        rd = librosa.feature.rms(y=yd, frame_length=hop * 2, hop_length=hop)[0]
        rd = rd[:len(rms)] if len(rd) >= len(rms) else np.pad(rd, (0, len(rms) - len(rd)))
    else:
        log("⚠️ thiếu 02_tieng/htdemucs/drums.wav — mọi khoảng đoán «cam_xuc»")
        rd = np.zeros_like(rms)
    ra, a = [], None
    for i, c in enumerate(co):
        t = i * 0.5
        if c and a is None:
            a = t
        elif not c and a is not None:
            ra.append([a, t]); a = None
    if a is not None:
        ra.append([a, len(co) * 0.5])
    gop = []
    for k in ra:
        if gop and k[0] - gop[-1][1] < 2.0:
            gop[-1][1] = k[1]
        else:
            gop.append(k)
    gop = [k for k in gop if k[1] - k[0] >= 4.0]
    cues = []
    for k in gop:
        i1, i2 = int(k[0] / 0.5), max(int(k[0] / 0.5) + 1, int(k[1] / 0.5))
        e_all = float(np.mean(rms[i1:i2])) + 1e-8
        ty = float(np.mean(rd[i1:i2])) / e_all
        muc = float(np.mean(db[i1:i2]))
        mood = "hanh_dong" if (ty > 0.55 and muc > san + 12) else "hoi_hop" if ty > 0.35 else "cam_xuc"
        cues.append({"start": round(k[0], 1), "end": round(k[1], 1), "mood": mood, "nang_luong_db": round(muc, 1), "ty_le_drums": round(ty, 2)})
    return cues, san


def chia_canh(cues, moc_noi):
    """Khoảng > 75 s ⇒ cảnh 25–75 s: cắt ở mốc nối tập (hai bên ≥ 25 s), phần còn dài thì chia đều. Giữ tâm trạng. Không dùng model."""
    ra = []
    for c in cues:
        if c["end"] - c["start"] <= CANH_MAX:
            ra.append(c); continue
        moc = [c["start"]]
        for m in sorted(moc_noi):
            if m - moc[-1] >= CANH_MIN and c["end"] - m >= CANH_MIN:
                moc.append(m)
        moc.append(c["end"])
        doan = []
        for a, b in zip(moc, moc[1:]):
            n = max(1, math.ceil((b - a) / CANH_MAX))
            doan += [(a + (b - a) * i / n, a + (b - a) * (i + 1) / n) for i in range(n)]
        for a, b in doan:
            ra.append({**c, "start": round(a, 1), "end": round(b, 1), "chia_tu": [c["start"], c["end"]]})
        log(f"chia cảnh {c['start']:.0f}–{c['end']:.0f}s → {[round(a) for a, _ in doan]} ({c['mood']})")
    return ra


def kho_bai(kho):
    return {m: sorted(f for duoi in DUOI for f in kho.glob(f"{m}_*.{duoi}")) for m in MO_TA_MOOD}


def chon_bai(cues, kho, dung_bai_co_san):
    ds_kho = kho_bai(kho)
    tat_ca = sorted(f for duoi in DUOI for f in kho.glob(f"*.{duoi}"))
    dem = {m: 0 for m in MO_TA_MOOD}
    truoc = None
    for c in cues:
        ds = ds_kho.get(c["mood"]) or (tat_ca if dung_bai_co_san else [])
        if not ds:
            c["file"] = None; continue
        dem.setdefault(c["mood"], 0)
        for _ in range(len(ds)):
            f = ds[dem[c["mood"]] % len(ds)]; dem[c["mood"]] += 1
            if str(f) != truoc or len(ds) == 1:
                break
        c["file"] = str(f); truoc = str(f)
    return cues


def tuong_doi(p, d):
    """Đường dẫn trong thư mục tập ghi tương đối (chép tập sang máy khác vẫn chạy)."""
    try:
        return str(Path(p).resolve().relative_to(d.resolve()))
    except ValueError:
        return str(p)


def kiem_cue(cu, d):
    """nhac_cue.json sửa tay (--giu-cue): đúng dạng {"cues": [{start, end, mood, file?, gain_db?}]} — sai thì dừng với câu rõ."""
    if not isinstance(cu, dict) or not isinstance(cu.get("cues"), list):
        sys.exit('🔴 06_nhac/nhac_cue.json sai dạng: cần {"cues": [{"start", "end", "mood", "file", "gain_db"}, …]}')
    loi = []
    for i, c in enumerate(cu["cues"], 1):
        if not isinstance(c, dict):
            loi.append(f"khoảng {i}: không phải object"); continue
        try:
            a_, b_ = float(c["start"]), float(c["end"])
            if not (math.isfinite(a_) and math.isfinite(b_)):
                raise ValueError("nan/inf")
            if not 0 <= a_ < b_:
                loi.append(f"khoảng {i}: cần 0 ≤ start < end (đang {a_}–{b_})")
            c["start"], c["end"] = a_, b_
        except (KeyError, TypeError, ValueError):
            loi.append(f"khoảng {i}: thiếu / sai số start, end")
        if not isinstance(c.get("mood"), str) or not c["mood"]:
            loi.append(f"khoảng {i}: thiếu «mood»")
        try:
            if not math.isfinite(float(c.get("gain_db") or 0)):
                raise ValueError("nan/inf")
        except (TypeError, ValueError):
            loi.append(f"khoảng {i}: gain_db «{c.get('gain_db')}» không phải số")
        f = c.get("file")
        if f is not None and not isinstance(f, str):
            loi.append(f"khoảng {i}: «file» phải là chuỗi đường dẫn hoặc null")
        elif f and not (Path(f) if Path(f).is_absolute() else d / f).is_file():
            loi.append(f"khoảng {i}: không thấy tệp nhạc «{f}»")
    if loi:
        sys.exit("🔴 06_nhac/nhac_cue.json có lỗi — sửa rồi chạy lại --giu-cue:\n  " + "\n  ".join(loi[:20]))
    return cu["cues"], cu.get("san_db")


def ghep_bed(cues, tong, ra, d):
    ins, filt, n = [], [], 0
    for c in cues:
        if not c.get("file"):
            continue
        f = Path(c["file"]) if Path(c["file"]).is_absolute() else d / c["file"]
        dai = c["end"] - c["start"]
        src = ffprobe_dur(f)
        ins += ["-i", str(f)]
        loop = f"aloop=loop=-1:size={int(src * 44100)}," if src < dai else ""
        filt.append(f"[{n}:a]aresample=44100,aformat=channel_layouts=stereo,{loop}atrim=0:{dai:.2f},afade=t=in:d=1.0,afade=t=out:st={max(0, dai - 1.5):.2f}:d=1.5,"
                    f"volume={float(c.get('gain_db') or 0):.2f}dB,adelay={int(c['start'] * 1000)}|{int(c['start'] * 1000)}[m{n}]")
        n += 1
    if n == 0:
        chay([can("ffmpeg"), "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo:d={tong:.2f}", "-c:a", "pcm_s16le", ra])
        return 0
    fc = ";".join(filt) + ";" + "".join(f"[m{i}]" for i in range(n)) + \
        f"amix=inputs={n}:normalize=0:duration=longest,apad=whole_dur={tong:.2f},atrim=0:{tong:.2f}[b]"
    chay([can("ffmpeg"), "-hide_banner", "-v", "error", "-y", *ins, "-filter_complex", fc, "-map", "[b]", "-ac", "2", "-c:a", "pcm_s16le", ra])
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m ptm.b6_nhac", description="B6 — nhạc nền đúng chỗ")
    ap.add_argument("--tap", required=True)
    ap.add_argument("--giu-cue", action="store_true", help="dùng 06_nhac/nhac_cue.json đã sửa tay, không dò lại")
    ap.add_argument("--mot-bai", help="một tệp nhạc dùng cho mọi khoảng")
    ap.add_argument("--khong-nhac", action="store_true", help="không đặt nhạc nền (B7 chỉ trộn tiếng gốc + giọng)")
    ap.add_argument("--dung-bai-co-san", action="store_true", help="tâm trạng thiếu bài thì mượn bài khác trong kho, không xin phiếu")
    a = ap.parse_args(argv)
    can("ffmpeg"); can("ffprobe")
    d = tap_dir(a.tap)
    t = doc_tap(a.tap)
    ng = d / "06_nhac"; ng.mkdir(exist_ok=True)
    kho = ng / "kho"; kho.mkdir(exist_ok=True)
    cue_f = ng / "nhac_cue.json"
    if a.khong_nhac:
        (ng / "nhac_bed.wav").unlink(missing_ok=True)
        ghi_json(cue_f, {"cues": [], "khong_nhac": True})
        log("bỏ nhạc nền theo --khong-nhac")
        xong_buoc(a.tap, "b6_nhac", khong_nhac=True, so_cue=0)
        return
    t0 = time.time()
    if a.giu_cue and cue_f.exists():
        try:
            cu = json.loads(cue_f.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as e:
            sys.exit(f"🔴 06_nhac/nhac_cue.json không đọc được (JSON hỏng): {str(e)[:120]}")
        if isinstance(cu, dict) and cu.get("khong_nhac"):   # đã chọn --khong-nhac: --giu-cue không được lặng lẽ bật nhạc lại
            (ng / "nhac_bed.wav").unlink(missing_ok=True)
            log("tập đã chọn KHÔNG nhạc (--khong-nhac) — giữ nguyên. Muốn có nhạc: chạy lại B6 không kèm --giu-cue")
            xong_buoc(a.tap, "b6_nhac", khong_nhac=True, so_cue=0)
            return
        cues, san = kiem_cue(cu, d)
    else:
        nhac_goc = d / "02_tieng/nhac_goc.wav"
        if not nhac_goc.exists():
            sys.exit("🔴 Thiếu 02_tieng/nhac_goc.wav — chạy B2 trước (hoặc --khong-nhac)")
        cues, san = do_khoang_nhac(nhac_goc, d / "02_tieng/htdemucs/drums.wav")
        cues = chia_canh(cues, [round(m["bat_dau"]) for m in (t.get("cac_tap") or [])[1:]])
    if a.mot_bai:
        f = Path(a.mot_bai).expanduser().resolve()
        if not f.exists():
            sys.exit(f"🔴 Không thấy tệp nhạc {f}")
        for c in cues:
            c["file"] = tuong_doi(f, d)
    else:   # --giu-cue: chỉ chọn bài cho khoảng còn trống (vd sau khi trợ lý bỏ bài vào kho)
        trong = [c for c in cues if not c.get("file")] if a.giu_cue else cues
        chon_bai(trong, kho, a.dung_bai_co_san)
        for c in trong:
            c["file"] = tuong_doi(c["file"], d) if c.get("file") else None
    thieu = sorted({c["mood"] for c in cues if not c.get("file")})
    if thieu:
        ghi_json(cue_f, {"san_db": san, "cues": cues, "ghi_chu": "Sửa start/end/mood/file/gain_db rồi chạy lại B6 với --giu-cue"})
        giay = {m: round(sum(c["end"] - c["start"] for c in cues if c["mood"] == m)) for m in thieu}
        cho_tro_ly(ng / "CAN_NHAC.json", f"Cần nhạc nền cho {len(thieu)} tâm trạng: {', '.join(thieu)}",
                   cong_cu="Làm nhạc nền không lời (hgnhac)", thu_muc_tap=str(d),
                   cach_lam=["Mỗi tâm trạng: gọi món «Làm nhạc nền không lời» với «mo_ta» (tiếng Anh) — món trả clip ~30 giây, máy tự lặp cho đủ dài.",
                             "Tải mp3 về đúng «luu_vao» (có thể nhiều bài: <tâm_trạng>_02.mp3 …), hoặc người dùng tự bỏ bài nhạc có quyền dùng vào 06_nhac/kho/.",
                             f"Xong chạy lại: python -m ptm.b6_nhac --tap {a.tap} --giu-cue",
                             f"Không muốn nhạc: python -m ptm.b6_nhac --tap {a.tap} --khong-nhac · một bài cho cả phim: --mot-bai <tệp>"],
                   nhac=[{"mood": m, "mo_ta": "Instrumental only, no vocals. " + MO_TA_MOOD.get(m, m) + ". Starts immediately, no long intro.",
                          "luu_vao": f"06_nhac/kho/{m}_01.mp3", "tong_giay_can": giay[m]} for m in thieu])
    (ng / "CAN_NHAC.json").unlink(missing_ok=True)
    tong = (t.get("video") or {}).get("dur") or ffprobe_dur(d / "01_raw/goc.mp4")
    n = ghep_bed(cues, tong, ng / "nhac_bed.wav", d)
    ghi_json(cue_f, {"san_db": san, "cues": cues, "ghi_chu": "Sửa start/end/mood/file/gain_db rồi chạy lại B6 với --giu-cue"})
    phu = sum(c["end"] - c["start"] for c in cues)
    log(f"{len(cues)} khoảng nhạc, phủ {phu:.0f}/{tong:.0f}s ({phu / tong * 100:.0f}%) · {n} có bài · {time.time() - t0:.0f}s")
    for c in cues:
        print(f"  {c['start']:7.1f}–{c['end']:7.1f} {c['mood']:10} {Path(c['file']).name if c.get('file') else '—'}")
    xong_buoc(a.tap, "b6_nhac", so_cue=len(cues), phu_giay=round(phu), co_bai=n)


if __name__ == "__main__":
    main()
