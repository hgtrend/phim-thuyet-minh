"""B2 — TÁCH TIẾNG: bỏ nhạc, giữ giọng Trung + SFX.

Demucs htdemucs tách 4 lớp: vocals (giọng, tiếng thở, hét) · drums (va đập, nổ — phần lớn SFX nằm đây) · bass · other (giai điệu, đệm).
Lớp giữ lại gộp thành `02_tieng/tieng_sfx.wav` (vào bản dựng); các lớp còn lại gộp thành `02_tieng/nhac_goc.wav`
(chỉ để B6 dò chỗ nào nguồn có nhạc, KHÔNG vào bản dựng).

    python -m ptm.b2_tach_tieng --tap <slug> [--sfx-stems vocals,drums] [--thiet-bi cuda|mps|cpu]

--sfx-stems: các lớp gộp vào tieng_sfx.wav (vocals luôn có). Mặc định «vocals,drums».
  «vocals»        — chỉ giọng: khi nghe thấy drums mang theo trống của nhạc.
  «vocals,drums,other» — khi SFX (gió, sét, phép) nằm ở other.
Chọn bằng TAI: nghe thử tieng_sfx.wav rồi chạy lại với lớp khác (xoá tieng_sfx.wav không cần, máy ghi đè).
"""
import argparse, json, math, re, subprocess, sys, time

from .chung import can, chay, ffprobe_dur, log, tap_dir, thiet_bi, xong_buoc

LOP = ("vocals", "drums", "bass", "other")


def do_lufs(f):
    p = subprocess.run([can("ffmpeg"), "-hide_banner", "-v", "info", "-i", str(f), "-af",
                        "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    bang = [b for b in re.findall(r"\{[^{}]+\}", p.stderr) if '"input_i"' in b]   # bảng đo loudnorm là khối CUỐI
    try:
        v = float(json.loads(bang[-1]).get("input_i")) if bang else None
    except (TypeError, ValueError):
        return None
    return v if v is not None and math.isfinite(v) else None


def tron(ffmpeg, vao, ra):
    """Gộp các wav (cộng thẳng, không chuẩn hoá) thành một wav 16-bit."""
    ins = []
    for f in vao:
        ins += ["-i", f]
    if len(vao) == 1:
        chay([ffmpeg, "-hide_banner", "-v", "error", "-y", *ins, "-c:a", "pcm_s16le", ra])
    else:
        chay([ffmpeg, "-hide_banner", "-v", "error", "-y", *ins, "-filter_complex",
              f"amix=inputs={len(vao)}:normalize=0:duration=longest", "-c:a", "pcm_s16le", ra])


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m ptm.b2_tach_tieng", description="B2 — tách giọng + SFX khỏi nhạc (Demucs htdemucs)")
    ap.add_argument("--tap", required=True)
    ap.add_argument("--sfx-stems", default="vocals,drums",
                    help="lớp gộp vào tieng_sfx.wav, cách nhau dấu phẩy (vocals luôn có). Mặc định vocals,drums; chỉ giọng: vocals")
    ap.add_argument("--thiet-bi", choices=["cuda", "mps", "cpu"], default=None, help="mặc định tự chọn: cuda → mps → cpu")
    a = ap.parse_args(argv)
    giu = [s.strip() for s in a.sfx_stems.split(",") if s.strip()]
    sai = [s for s in giu if s not in LOP]
    if sai:
        sys.exit(f"🔴 --sfx-stems có lớp lạ {sai}; chỉ dùng: {', '.join(LOP)}")
    giu = ["vocals"] + [s for s in LOP[1:] if s in giu]          # vocals luôn đứng đầu, thứ tự cố định
    con_lai = [s for s in LOP[1:] if s not in giu]
    tb = a.thiet_bi or thiet_bi()
    ffmpeg = can("ffmpeg")

    d = tap_dir(a.tap)
    goc = d / "01_raw" / "goc.mp4"
    if not goc.exists():
        sys.exit("🔴 thiếu 01_raw/goc.mp4 — chạy B1 trước")
    ra = d / "02_tieng"
    ra.mkdir(exist_ok=True)
    stems = ra / "htdemucs"
    t0 = time.time()
    if not all((stems / f"{s}.wav").exists() for s in LOP):
        # rút tiếng nguồn ra wav 44,1k trước cho demucs khỏi đọc container mp4
        chay([ffmpeg, "-hide_banner", "-v", "error", "-y", "-i", goc, "-vn", "-ac", "2", "-ar", "44100", ra / "goc.wav"])
        try:
            import demucs  # noqa: F401
        except ImportError:
            sys.exit("🔴 Thiếu Demucs: «pip install demucs»")
        log(f"Demucs htdemucs trên {tb} …")
        try:
            chay([sys.executable, "-m", "demucs", "-n", "htdemucs", "-d", tb, "-o", ra, "--filename", "{stem}.wav", ra / "goc.wav"])
        except subprocess.CalledProcessError:
            if tb == "cpu":
                raise
            log(f"⚠️ Demucs hỏng trên {tb} ⇒ chạy lại trên cpu")
            chay([sys.executable, "-m", "demucs", "-n", "htdemucs", "-d", "cpu", "-o", ra, "--filename", "{stem}.wav", ra / "goc.wav"])
            tb = "cpu"
    for s in LOP:
        if not (stems / f"{s}.wav").exists():
            sys.exit(f"🔴 demucs không ra {s}.wav")
    tron(ffmpeg, [stems / f"{s}.wav" for s in giu], ra / "tieng_sfx.wav")
    if con_lai:
        tron(ffmpeg, [stems / f"{s}.wav" for s in con_lai], ra / "nhac_goc.wav")
    else:
        log("⚠️ mọi lớp đều vào tieng_sfx ⇒ nhac_goc.wav im lặng")
        chay([ffmpeg, "-hide_banner", "-v", "error", "-y", "-i", stems / "vocals.wav", "-af", "volume=0", "-c:a", "pcm_s16le", ra / "nhac_goc.wav"])
    so = {"giay_tach": round(time.time() - t0), "thiet_bi": tb, "sfx_stems": [s for s in giu if s != "vocals"],
          "lufs_vocals": do_lufs(stems / "vocals.wav"), "lufs_tieng_sfx": do_lufs(ra / "tieng_sfx.wav"),
          "lufs_nhac_goc": do_lufs(ra / "nhac_goc.wav"), "dur": round(ffprobe_dur(ra / "tieng_sfx.wav"), 2)}
    log(f"xong: tieng_sfx ({'+'.join(giu)}) {so['lufs_tieng_sfx']} LUFS · nhac_goc {so['lufs_nhac_goc']} LUFS · {so['giay_tach']}s")
    xong_buoc(a.tap, "b2_tach_tieng", **so)


if __name__ == "__main__":
    main()
