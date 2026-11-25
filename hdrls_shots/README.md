# HDRLS Shot Manager

HDR Light Studio (Lightmap) Blender bağlantısı için ek eklenti: her **shot**
(frame aralığı) için ayrı bir HDR Light Studio ışık projesi tutar, hepsini
`.blend` dosyasına kaydeder ve frame başka bir shot'a geçince canlı HDR Light
Studio oturumunu o shot'un ışığıyla yeniden açar.

## Nasıl çalışır

- HDR Light Studio bağlantısı bütün projeyi `scene["HDRLS Project Data"]`
  içinde XML olarak tutar ve *Start*'ta oradan yükler.
- Her shot bu XML'in kendi kopyasını saklar. Frame değişince eklenti:
  1. bağlantının kayıt fonksiyonuyla güncel projeyi alır, eski shot'a yazar
     ve canlı düşük çözünürlüklü HDRI'yi `*_preview.hdr` olarak kopyalar,
  2. `Stop` → yeni shot'un XML'ini sahneye koyar → `Start`.
- Dosya kaydedilirken (HDR Light Studio kendi verisini yazdıktan sonra) canlı
  proje, aktif shot'a da yazılır.
- Shot, başlangıç frame'inden bir sonraki shot'un başladığı frame'e kadar sürer
  (kamera marker'ları gibi). İlk shot'tan önceki frame'ler ilk shot'a aittir.

## Kurulum

*Edit ▸ Preferences ▸ Add-ons ▸ (sağ üst menü) Install from Disk…* →
`hdrls_shot_manager.py` → etkinleştirin. HDR Light Studio bağlantı eklentisi de
etkin olmalıdır.

Panel: **Properties ▸ World ▸ HDRLS Shots** ve 3B görünümde **N ▸ HDRLS**.

## Kullanım

1. `.blend` dosyasını kaydedin (shot HDRI'leri `//hdrls_shots/` klasörüne yazılır).
2. HDR Light Studio'yu her zamanki gibi başlatın.
3. İlk frame'e gidin → **+** (Add Shot). O anki ışık "F001" shot'u olur.
4. Işığın değişeceği frame'e gidin → **+**. Yeni shot o anki ışığın kopyasıyla
   başlar, HDR Light Studio yeniden açılmaz; ışığı düzenleyin.
5. Timeline'da frame değiştirdikçe ilgili shot otomatik yüklenir
   (oynatma ve hızlı scrub sırasında beklenir, durunca geçilir).
   Listedeki ▶ düğmesi shot'a gider ve yükler.
6. Kaydettiğinizde bütün shot'lar `.blend` içinde saklanır; dosyayı başka bir
   oturumda açıp kaldığınız yerden devam edersiniz.

## Final render

- **Set HDRLS Render Path** açıkken her shot'un HDR Light Studio *Render*
  çıktısı `//hdrls_shots/<shot adı>.hdr|.exr` olur. Bir shot canlıyken HDR Light
  Studio'da yüksek çözünürlüklü render alın; dosya doğrudan o shot'a ait olur.
- **Use Shots World**: sahneyi `HDRLS Shots World`'e geçirir; tek bir
  Environment Texture'ın görüntüsü her frame'de o shot'un HDRI'sine (yoksa
  preview'a) çevrilir — animasyon render'ında da çalışır. Yeni HDRI
  render ettikten sonra **Reload Shot HDRIs**.
- **Use Live World**: canlı düzenleme için `HDRLS World`'e geri döner.
- Animasyon render'ında *Render ▸ Lock Interface* açık olması önerilir.

## Ayarlar

| Ayar | Açıklama |
|---|---|
| Auto Switch on Frame Change | Frame değişince shot'u otomatik yükle |
| Restart Live Session | Geçişte HDR Light Studio'yu Stop/Start et. Kapalıyken yalnızca `.blend` içindeki veri değişir; bir sonraki Start o shot'u açar |
| Sync Before Storing | Saklamadan önce bağlantıdan güncel projeyi iste |
| Switch Delay | Son frame değişiminden sonra bekleme (scrub sırasında boşuna yeniden başlatmayı önler) |
| Restart Wait | Stop ile Start arasındaki bekleme; HDR Light Studio geç kapanıyorsa artırın |
| Reload into HDR Light Studio | Canlı oturum shot'tan saparsa, shot'un kayıtlı ışığıyla yeniden başlat |

## Sınırlar

- HDR Light Studio'nun veri formatı ve iç fonksiyonları belgelenmemiştir;
  bağlantı eklentisinin yeni sürümleri davranışı değiştirebilir.
- Her geçişte HDR Light Studio yeniden başladığı için birkaç saniyelik bekleme olur.
- `hdrls_probe.py`: sorun olursa Text Editor'de çalıştırın; `HDRLS_Rapor`
  metin bloğu eklentilerin sahneye yazdıklarını, operatörleri ve handler'ları listeler.
