# Vitarg v1.0.3 - Kapsamlı Kod Denetimi ve Hata Raporu (Bug Audit Report)

**Tarih**: 16 Kasım 2026  
**Hedef Sürüm**: v1.0.3 (Commit: `3866051`)  
**Denetim Kapsamı**: v1.0.3 ile eklenen ve güncellenen tüm özellikler, Windows & Linux uyumluluğu, çalışma zamanı (runtime) istisnaları, iş parçacığı (threading) güvenliği ve CI/CD derleme testi riskleri.  
**Durum**: Analiz tamamlandı. Kodlarda **hiçbir değişiklik yapılmadı** (Kullanıcı talimatı: *düzeltme işi sonra, bulunan hataları dosyaya yaz*).

---

## Özet Tablo

| ID | Önem Derecesi | Dosya / Satır | Başlık | Tetiklenme Durumu |
|---|---|---|---|---|
| **BUG-01** | **CRITICAL** | `vitarg/engine.py:53, 286` | `alac` codec'inin FFmpeg için geçerli bir çıktı konteyneri olmaması | Herhangi bir sesi ALAC'a dönüştürme ve CI `test_audio_pairs` testi |
| **BUG-02** | **HIGH** | `vitarg/tools.py:809` | `extract_text_tool` görsel fallback'inde `KeyError: 'dimensions'` çökmesi | Görselden metin çıkarma (pytesseract yokken/başarısızken) |
| **BUG-03** | **HIGH** | `vitarg/tools.py:752, 786` | `volume_boost` ve `audio_equalizer` araçlarının WebM videolarında FFmpeg hatası vermesi | WebM videolarında ses yükseltme veya ekolayzır çalıştırma |
| **BUG-04** | **HIGH** | `vitarg/dialogs.py:627` | `ClipboardConvertDialog._do_save` format dönüşümü yapmadan BGRA tamponu varsayıyor | Linux (X11/Wayland) ortamında 24-bit RGB veya RGBA pano görselleri |
| **BUG-05** | **MEDIUM** | `vitarg/tools.py:816-823` | `extract_text_tool` arka plan iş parçacığından (QThread) `QClipboard` erişimi | "Copy to Clipboard" veya "Both" hedefi seçildiğinde |
| **BUG-06** | **MEDIUM** | `vitarg/dialogs.py:560, 608`, `vitarg/app.py:330` | `PdfOrganizerDialog` tüm dosyalar silindiğinde boş belgeyle `fitz.FileDataError` çökmesi | Listeden tüm sayfalar/dosyalar çıkarılıp "Create PDF" basıldığında |
| **BUG-07** | **MEDIUM** | `vitarg/dialogs.py:253` | Linux'ta ses önizlemede `ffplay` grafik pencere açıp iş parçacığını bloke ediyor | Linux ortamında ses önizleme (2s) dinleme butonuna basıldığında |
| **BUG-08** | **LOW** | `vitarg/jobs.py:182` | Arşiv çıkarma (`extract`) sonrasında boyut farkı kartında yanıltıcı istatistik | Klasöre çıkartılan ZIP/TAR/7Z arşivlerinde |
| **BUG-09** | **LOW** | `vitarg/app.py:164-168` | Sistem tepsisi olan Linux masaüstlerinde (GNOME/KDE) Drop Target'ın varsayılan gizli kalması | Linux'ta ilk çalıştırmada sürükle-bırak hedefinin ekranda görünmemesi |
| **BUG-10** | **LOW** | `vitarg/settings.py:305, 323` | Linux Nautilus script ve KDE servicemenus içinde boşluklu python yollarının tırnaksız olması | Python yolu veya sanal ortam klasörü boşluk içerdiğinde |
| **BUG-11** | **LOW** | `vitarg/engine.py:336-340` | Sessiz video/GIF'ten AVI dönüşümünde `-q:a 3` parametresinin artık kalması | Sessiz kaynaktan AVI video üretildiğinde |
| **BUG-12** | **LOW** | `README.md` | v1.0.3 ile gelen 9 yeni özelliğin dökümantasyon tablosunda yer almaması | Kullanıcı dökümantasyonu incelediğinde |

---

## Detaylı Hata İncelemeleri

### BUG-01 [CRITICAL]: `alac` Ses Formatının FFmpeg Muxer Uyuşmazlığı ve CI Derleme Kırıcı Hata
- **Dosya**: `vitarg/engine.py` (Satır ~53 ve ~286)
- **Açıklama**: 
  v1.0.3 ile `AUDIO_OUT` listesine `"alac"` eklendi ve `AUDIO_CODEC["alac"] = ["-c:a", "alac"]` olarak tanımlandı.
  Ancak FFmpeg kütüphanesinde `alac` bir **dosya konteyneri/muxer değildir**, sadece Apple Lossless Audio Codec sıkıştırma algoritmasıdır (ALAC verisi standart olarak `.m4a` veya `.caf` konteyneri içinde saklanır).
  Kullanıcı bir sesi `alac` hedefine dönüştürmek istediğinde FFmpeg şu komutu çalıştırır:
  ```bash
  ffmpeg -i input.wav -map 0:a:0 -vn -c:a alac output.alac
  ```
  FFmpeg derhal şu hatayla çöker:
  ```
  [AVFormatContext @ ...] Unable to choose an output format for 'output.alac'; use a standard extension for the filename or specify the format manually.
  [out#0 @ ...] Error initializing the muxer for output.alac: Invalid argument
  ```
- **Kritik Etki**: 
  GitHub Actions CI derleme adımı (`build.yml`) `tests/test_engine.py` altındaki `test_audio_pairs` testini çalıştırmaktadır:
  ```python
  for tf in engine.targets_for_format("wav"):
      out = self.conv(src, tf)[0]
  ```
  `wav` için hedefler taranırken `alac` sıraya girdiğinde test `ConversionError` alacak ve **hem Windows hem Linux GitHub Actions derlemeleri 1 hata ile fail olacaktır!**
- **Önerilen Çözüm**:
  1. `alac` formatını `AUDIO_OUT` listesinden çıkarmak (yalnızca `AUDIO_IN`'de bırakmak, böylece ALAC dosyaları okunup diğer formatlara dönüştürülebilir).
  2. Veya ALAC çıktısı verilecekse dosya uzantısını `.m4a` olarak eşleyip `-f ipod` / `-c:a alac` kullanmak.

---

### BUG-02 [HIGH]: `extract_text_tool` Görsel Fallback Kodunda `KeyError: 'dimensions'` Çökmesi
- **Dosya**: `vitarg/tools.py` (Satır ~809)
- **Açıklama**:
  Görselden metin çıkarma aracında (`extract_text_tool`), `pytesseract` kütüphanesi kurulu olmadığında veya OCR hata verdiğinde, sistem dosya meta verilerini metin olarak döndürmek üzere fallback bloğuna düşer:
  ```python
  from .inspector import get_file_info
  info = get_file_info(src)
  text = f"File: {info['name']}\nDimensions: {info['dimensions']}\nFormat: {info['format']}\nSHA256: {info['sha256']}\n"
  ```
  Ancak `inspector.py` içindeki `get_file_info()` fonksiyonunun döndürdüğü sözlükte kök düzeyde `'dimensions'` anahtarı **YOKTUR**. Boyut bilgisi `info["media"]["Dimensions"]` altında tutulmaktadır.
- **Etki**:
  Sistemde tesseract OCR kurulu değilken herhangi bir görselden metin çıkarılmak istendiğinde araç derhal `KeyError: 'dimensions'` fırlatarak çöker.
- **Önerilen Çözüm**:
  Satırı güvenli erişimle güncellemek:
  ```python
  dims = info.get("media", {}).get("Dimensions", "N/A")
  text = f"File: {info['name']}\nDimensions: {dims}\nFormat: {info['format']}\nSHA256: {info['sha256']}\n"
  ```

---

### BUG-03 [HIGH]: `volume_boost` ve `audio_equalizer` Araçlarının WebM Videolarında Çökmesi
- **Dosya**: `vitarg/tools.py` (Satır ~752 ve ~786)
- **Açıklama**:
  `volume_boost` ve `audio_equalizer` fonksiyonlarında video dosyaları (`fam == "video"`) işlenirken ses kodeği sabit olarak AAC olarak kodlanmıştır:
  ```python
  if fam == "video":
      args = ["-i", str(src), "-c:v", "copy", "-filter:a", vol_filter, "-c:a", "aac", "-b:a", "192k", str(out)]
  ```
  Çıktı dosyası `out = _out(ws, src, ...)` ile kaynak dosyanın uzantısını alır. Eğer kaynak dosya bir `.webm` videosu ise çıktı da `.webm` uzantılı olur.
  WebM konteyneri standartları gereği AAC ses formatını **kesinlikle reddeder** (`Only VP8, VP9, AV1 video and Vorbis or Opus audio are supported for WebM`).
  FFmpeg şu hatayı vererek işlemi durdurur:
  ```
  [webm @ ...] Only VP8 or VP9 or AV1 video and Vorbis or Opus audio and WebVTT subtitles are supported for WebM.
  Could not write header (incorrect codec parameters ?): Invalid argument
  Conversion failed!
  ```
- **Etki**:
  Kullanıcı bir `.webm` videosunun sesini yükseltmek veya ekolayzır uygulamak istediğinde işlem %100 başarısız olur.
- **Önerilen Çözüm**:
  Video uzantısı kontrol edilerek WebM için opus veya vorbis atanmalıdır:
  ```python
  a_codec = ["-c:a", "libopus", "-b:a", "128k"] if sf == "webm" else ["-c:a", "aac", "-b:a", "192k"]
  args = ["-i", str(src), "-c:v", "copy", "-filter:a", vol_filter, *a_codec, str(out)]
  ```

---

### BUG-04 [HIGH]: `ClipboardConvertDialog._do_save` Ham Tamponu BGRA Olarak Varsayıyor (Linux Renk / Boyut Çökmesi)
- **Dosya**: `vitarg/dialogs.py` (Satır ~627)
- **Açıklama**:
  Panodaki görsel kaydedilirken şu kod çalıştırılmaktadır:
  ```python
  buffer = self.qimg.bits().tobytes()
  pil_im = Image.frombuffer("RGBA", (self.qimg.width(), self.qimg.height()), buffer, "raw", "BGRA", 0, 1)
  ```
  `QGuiApplication.clipboard().image()` işletim sistemine ve panoya kopyalayan uygulamaya göre farklı `QImage.Format` döndürür.
  Windows'ta çoğu zaman 32-bit BGRA gelirken, Linux ortamında (X11 / Wayland üzerinde GIMP, Spectacle, Flameshot, Firefox vb.) görsel panoya `Format_RGB888` (piksel başına 3 bayt) veya `Format_RGBA8888` olarak konur.
  Format `Format_RGB888` olduğunda tampon bayt sayısı `width * height * 4` yerine `width * height * 3` olur ve `Image.frombuffer` derhal şu hatayla çöker:
  ```
  ValueError: not enough image data / buffer is too small for requested array
  ```
  Eğer `Format_RGBA8888` ise kırmızı ile mavi kanalları yer değiştirir (kırmızı nesneler mavi çıkar).
- **Etki**:
  Linux kullanıcıları panodan ekran görüntüsü veya resim kaydetmek istediğinde hata penceresiyle karşılaşır veya renkler bozuk kaydedilir.
- **Önerilen Çözüm**:
  Tampon çıkarılmadan önce QImage standart bir formata dönüştürülmelidir:
  ```python
  conv = self.qimg.convertToFormat(QImage.Format_ARGB32)
  buffer = conv.bits().tobytes()
  pil_im = Image.frombuffer("RGBA", (conv.width(), conv.height()), buffer, "raw", "BGRA", 0, 1)
  ```

---

### BUG-05 [MEDIUM]: `extract_text_tool` Arka Plan İş Parçacığından `QClipboard` Erişimi
- **Dosya**: `vitarg/tools.py` (Satır ~816-823)
- **Açıklama**:
  ```python
  target = params.get("target", ".txt File")
  if target in ("Copy to Clipboard", "Both"):
      try:
          from PySide6.QtGui import QGuiApplication
          clip = QGuiApplication.clipboard()
          if clip:
              clip.setText(text)
      except Exception:
          pass
  ```
  `tools.run_tool()` çağrısı `jobs.py` içindeki `Worker(QThread)` arka plan iş parçacığı tarafından yürütülür.
  Qt mimarisinde `QClipboard` **yalnızca ana GUI iş parçacığından (Main Thread)** erişilebilir.
  İkincil iş parçacığından `QClipboard.setText()` çağrıldığında Qt konsola uyarı basar (`QObject: Cannot create children for a parent that is in a different thread`) ve panoya kopyalama işlemi sessizce başarısız olur.
- **Etki**:
  Kullanıcı "Copy to Clipboard" seçeneğini seçtiğinde metin panoya kopyalanmaz.
- **Önerilen Çözüm**:
  Kopyalama işlemini iş tamamlandığında (`JobWindow._done` veya sinyal mekanizması ile) ana iş parçacığı üzerinde tetiklemek.

---

### BUG-06 [MEDIUM]: `PdfOrganizerDialog` Tüm Dosyalar Silindiğinde `fitz.FileDataError` Çökmesi
- **Dosya**: `vitarg/dialogs.py` (Satır ~560, 608) ve `vitarg/app.py` (Satır ~330)
- **Açıklama**:
  `PdfOrganizerDialog` penceresinde kullanıcı "✖ Remove" butonuna basarak seçilen tüm dosyaları listeden kaldırabilir.
  Liste boşaldığında kullanıcı "Create PDF ⚡" butonuna basarsa:
  - `ordered_paths()` boş bir liste `[]` döndürür.
  - `app.py` içinde `all(engine.fmt_of(p) == "pdf" for p in paths)` boş liste için matematiksel olarak `True` döner ve `pdf_merge([], ws)` çağrılır.
  - `pdf_merge` boş bir PyMuPDF belgesi (`merged = fz.open()`) oluşturur ve `merged.save(...)` çağırır.
  - PyMuPDF şu hatayı fırlatır:
    ```
    fitz.FileDataError: cannot save an empty document
    ```
- **Etki**:
  Kullanıcı boş listeyle devam ettiğinde işlem hata penceresiyle sonuçlanır.
- **Önerilen Çözüm**:
  `PdfOrganizerDialog` içinde liste eleman sayısı 0 olduğunda "Create PDF" butonunu devre dışı bırakmak veya tıklandığında kullanıcıya uyarı vermek (`QMessageBox.warning(self, "No files", "Please keep at least one file to create a PDF.")`).

---

### BUG-07 [MEDIUM]: Linux'ta Ses Önizleme Sırasında `ffplay`'in Grafik Pencere Açması ve Bloke Olması
- **Dosya**: `vitarg/dialogs.py` (Satır ~253)
- **Açıklama**:
  `FormDialog._play_audio_sample` fonksiyonunda oluşturulan 2 saniyelik geçici WAV dosyası Linux'ta şu döngüyle çalınmaktadır:
  ```python
  for player in ("paplay", "aplay", "pw-play", "ffplay"):
      p = shutil.which(player)
      if p:
          subprocess.run([p, tmp_wav], capture_output=True)
          break
  ```
  Eğer sistemde `paplay`, `aplay` veya `pw-play` yoksa ve FFmpeg ile birlikte gelen `ffplay` seçilirse, `ffplay` varsayılan olarak bir SDL grafik penceresi (spektrum/dalga formu) açar ve pencere kapatılana kadar süreç sonlanmaz. `subprocess.run` süreci beklediği için arka plan iş parçacığı kilitli kalır.
- **Etki**:
  Linux kullanıcılarında önizleme butonuna basıldığında beklenmeyen bir siyah pencere açılır.
- **Önerilen Çözüm**:
  `ffplay` çalıştırılırken pencereyi engellemek ve süre bitince otomatik çıkmak için parametre eklenmelidir:
  ```python
  cmd = [p, "-nodisp", "-autoexit", tmp_wav] if player == "ffplay" else [p, tmp_wav]
  ```

---

### BUG-08 [LOW]: Arşiv Çıkarma İşlemlerinde Boyut Farkı Kartının Yanıltıcı Değer Göstermesi
- **Dosya**: `vitarg/jobs.py` (Satır ~182)
- **Açıklama**:
  İş tamamlandığında giriş ve çıkış boyutlarını karşılaştıran kod:
  ```python
  in_sz = sum(Path(s).stat().st_size for s in self.sources if Path(s).exists())
  out_sz = sum(Path(o).stat().st_size for o in outs if Path(o).exists())
  ```
  `extract` aracı çalıştırıldığında çıktı bir klasördür (`out` = klasör yolu).
  Klasör üzerinde `.stat().st_size` çağrıldığında Linux'ta inode blok boyutu olan 4096 bayt, Windows'ta ise 0 bayt döner.
  Sonuç olarak 500 MB'lık bir ZIP arşivi klasöre çıkartıldığında kullanıcıya "4 KB (%99.9 daha küçük, 499.9 MB kazanıldı)" gibi tamamen yanıltıcı bir istatistik kartı gösterilir.
- **Etki**:
  Kullanıcı arayüzünde yanıltıcı boyut gösterimi.
- **Önerilen Çözüm**:
  Çıktı klasör ise içeriğini özyinelemeli (recursive) toplamak:
  ```python
  def _item_sz(p):
      return sum(f.stat().st_size for f in p.rglob('*') if f.is_file()) if p.is_dir() else p.stat().st_size
  ```

---

### BUG-09 [LOW]: Linux Masaüstlerinde Sistem Tepsisi Varken Floating Drop Target'ın Gizli Kalması
- **Dosya**: `vitarg/app.py` (Satır ~164-168)
- **Açıklama**:
  Windows'ta Windows Explorer sürükleme kancası (`DragMonitor`) aktif olarak çalışır. Ancak Linux'ta `DragMonitor` devre dışıdır.
  Linux'ta sürükle-bırak yapabilmek için `DropTarget` masaüstü bileşeni tasarlanmıştır.
  Ancak `app.py` şu kuralı uygulamaktadır:
  ```python
  if QSystemTrayIcon.isSystemTrayAvailable():
      self.tray.show()
  elif sys.platform != "win32":
      self.drop_target.show()
      self.act_drop.setChecked(True)
  ```
  GNOME (AppIndicator uzantılı) veya KDE Plasma gibi modern masaüstlerinde `isSystemTrayAvailable()` her zaman `True` döner. Bu nedenle `drop_target.show()` **asla çağrılmaz**.
  Kullanıcı Linux'ta uygulamayı başlattığında ekranda hiçbir pencere görmez ve dosyaları sürükleyip bırakabileceği bir alan bulamaz (tepsiye sağ tıklayıp "Floating Drop Target"ı manuel açması gerekir).
- **Etki**:
  Linux kullanıcı deneyiminde sürükle-bırak özelliğinin keşfedilmesini zorlaştırır.
- **Önerilen Çözüm**:
  Linux ortamında tepsi olsa dahi `self.drop_target.show()` varsayılan olarak açık gelsin (veya Ayarlar'dan kapatılabilsin).

---

### BUG-10 [LOW]: Linux Bağlam Menüsü Entegrasyonunda Boşluklu Python Yollarının Tırnaksız Yazılması
- **Dosya**: `vitarg/settings.py` (Satır ~305, 323)
- **Açıklama**:
  `set_context_menu` fonksiyonunda Linux için oluşturulan script ve desktop dosyalarında:
  ```python
  exe = sys.executable if getattr(sys, "frozen", False) else f"{sys.executable} -m vitarg"
  script_path.write_text(f'#!/bin/bash\n{exe} "$@"\n', encoding="utf-8")
  ...
  f"Exec={exe} %F\n"
  ```
  Eğer Python çalıştırıcısı boşluk içeren bir dizindeyse (örneğin `/home/user/Python Projects/venv/bin/python`), script ve KDE masaüstü eylemi komutu parçalayarak çalıştırma hatası verir.
- **Etki**:
  Boşluklu dizinlerde Linux bağlam menüsü çalışmaz.
- **Önerilen Çözüm**:
  `exe` değişkeni tanımlanırken tırnak içine alınmalıdır: `f'"{sys.executable}" -m vitarg'`.

---

### BUG-11 [LOW]: Sessiz Video / GIF'ten AVI Dönüşümünde `-q:a 3` Parametresinin Temizlenmemesi
- **Dosya**: `vitarg/engine.py` (Satır ~336-340)
- **Açıklama**:
  Ses akışı bulunmayan bir videodan veya GIF'ten AVI üretilirken ses parametreleri temizlenmektedir:
  ```python
  if a in ("-c:a", "-b:a"):
      skip_next = True
      continue
  ```
  Ancak `_video_args("avi", ...)` çıktısında ses kalite parametresi `-q:a 3` yer almaktadır. `-q:a` atlanmadığı için FFmpeg'e hem `-an` (sesi kapat) hem de `-q:a 3` gönderilmektedir.
- **Etki**:
  Modern FFmpeg bu parametreyi yoksaysa da komut satırında gereksiz bir argüman kalmaktadır.
- **Önerilen Çözüm**:
  Atlama kontrolüne `"-q:a"` eklenmelidir: `if a in ("-c:a", "-b:a", "-q:a"):`.

---

### BUG-12 [LOW]: `README.md` Dökümantasyonunda v1.0.3 Özelliklerinin Eksik Olması
- **Dosya**: `README.md`
- **Açıklama**:
  `README.md` dosyasındaki "Tools Wheel" ve "Smart Productivity Tools" bölümlerinde v1.0.3 ile eklenen 9 yeni özellik (Hedef Boyutlu Video Sıkıştırma, %600 Ses Yükseltme, Ekolayzır, Metin Çıkarma, Pano Dönüştürme Açılır Penceresi, Görsel PDF Düzenleyici, Boyut Karşılaştırma Kartı, Masaüstü Bağlam Menüsü Entegrasyonu) henüz listelenmemiştir.
- **Etki**:
  GitHub deposunu inceleyen kullanıcılar yeni özelliklerden haberdar olamaz.
- **Önerilen Çözüm**:
  `README.md` tablosuna ve özellik listesine v1.0.3 araçlarının eklenmesi.

---

## Sonuç ve Önerilen Eylem Planı
Yukarıdaki hatalar tespit edilmiş ve belgelenmiştir. Kod tabanında herhangi bir değişiklik yapılmamıştır.
Sen onay verdiğinde:
1. Öncelikli olarak derlemeyi kıran ve çökmeye yol açan **BUG-01 (alac)**, **BUG-02 (KeyError dimensions)**, **BUG-03 (WebM volume/eq)** ve **BUG-04 (Linux clipboard BGRA)** düzeltilecektir.
2. Ardından iş parçacığı güvenliği ve UI/UX hataları (**BUG-05**, **BUG-06**, **BUG-07**, **BUG-08**, **BUG-09**, **BUG-10**, **BUG-11**, **BUG-12**) çözülecektir.
3. Birim testleri (`test_logic.py` ve yeni eklenen özellik testleri) çalıştırılarak tam doğrulama sağlanacaktır.
