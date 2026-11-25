# HDRLS Shot Manager

HDR Light Studio (Lightmap) Blender bağlantısı için ek eklenti: her **shot**
(frame aralığı) için ayrı bir HDR Light Studio ışık projesi tutar, hepsini
`.blend` dosyasına kaydeder ve frame başka bir shot'a geçince canlı HDR Light
Studio oturumunu o shot'un ışığıyla yeniden açar.

## Nasıl çalışır

HDR Light Studio bağlantısı bütün projeyi `scene["HDRLS Project Data"]` içinde
XML olarak tutar. Bağlantının kendi fonksiyonları `Connection.saveProjectData()`
(HDR Light Studio → sahne) ve `Connection.loadHDRLSProjectData()` (sahne → çalışan
HDR Light Studio, *Start*'ın kullandığı çağrı) ile proje, programı kapatmadan
alınıp verilebilir.

İki mod vardır (panelin üstünde):

- **Light Looks** (varsayılan): tek bir HDR Light Studio projesi; her shot o
  projedeki bir *Light Look*'a bağlıdır. Frame başka bir shot'a geçince eklenti
  projedeki aktif Look'u (`<LightingLooks><current>`) o shot'un Look'u yapar ve
  projeyi çalışan HDR Light Studio'ya yükler. Look'lar zaten projenin içinde
  olduğundan hepsi `.blend` ile kaydedilir.
- **Separate Projects**: her shot projenin tam bir kopyasını saklar (v0.1
  davranışı); geçişte eski shot'un projesi saklanır, yenisi yüklenir.

Her iki modda geçiş varsayılan olarak **Live Load** ile yapılır (yeniden başlatma
yok). *Settings ▸ Switch Method ▸ Restart* eski Stop/Start yöntemidir.

Shot, başlangıç frame'inden bir sonraki shot'un başladığı frame'e kadar sürer
(kamera marker'ları gibi). İlk shot'tan önceki frame'ler ilk shot'a aittir.

## Kurulum

*Edit ▸ Preferences ▸ Add-ons ▸ (sağ üst menü) Install from Disk…* →
`hdrls_shot_manager.py` → etkinleştirin. HDR Light Studio bağlantı eklentisi de
etkin olmalıdır.

Panel: **Properties ▸ World ▸ HDRLS Shots** ve 3B görünümde **N ▸ HDRLS**.

## Kullanım (Light Looks)

1. `.blend` dosyasını kaydedin (shot HDRI'leri `//hdrls_shots/` klasörüne yazılır).
2. HDR Light Studio'yu her zamanki gibi başlatın.
3. HDR Light Studio'da ilk frame'in Look'unu aktif yapın; Blender'da ilk frame'e
   gidip **+** (Add Shot) basın. Shot aktif Look'a bağlanır ve onun adını alır.
4. HDR Light Studio'da yeni bir Look oluşturun / çoğaltın ve aktif yapın;
   ışığın değişeceği frame'e gidip **+** basın.
5. Timeline'da frame değiştirdikçe ilgili Look canlı olarak yüklenir
   (oynatma ve hızlı scrub sırasında beklenir, durunca geçilir).
6. Bir shot'un Look'unu değiştirmek için: listeden shot'u seçin, **Light Look**
   alanından seçin ya da HDR Light Studio'da Look'u aktif yapıp damlalık
   (*Use Active Look*) düğmesine basın. Look listesi ↻ ile yenilenir.
   Look HDR Light Studio'da yeniden adlandırılırsa kimliğinden bulunur.

> Look'lar ışıkları paylaşabilir: iki Look aynı ışığı içeriyorsa birinde yapılan
> değişiklik ötekini de etkiler. Shot'lar bağımsız olsun istiyorsanız Look'u
> HDR Light Studio'da ışıklarıyla birlikte çoğaltın.

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
| Switch Method | *Live Load*: çalışan HDR Light Studio'ya yükle (hızlı). *Restart*: Stop/Start (yavaş, yedek yöntem) |
| Update Live Session | Kapalıyken yalnızca `.blend` içindeki veri değişir; bir sonraki Start o shot'u açar |
| Sync Before Storing | Saklamadan önce bağlantıdan güncel projeyi iste |
| Switch Delay | Son frame değişiminden sonra bekleme (scrub sırasında boşuna yeniden başlatmayı önler) |
| Restart Wait | *Restart* yönteminde Stop ile Start arasındaki bekleme |
| Reload into HDR Light Studio | Canlı oturum shot'tan saparsa, shot'un Look'unu / kayıtlı ışığını yeniden gönder |

## Sınırlar

- HDR Light Studio'nun veri formatı ve iç fonksiyonları belgelenmemiştir;
  bağlantı eklentisinin yeni sürümleri davranışı değiştirebilir.
- *Live Load* her geçişte projeyi HDR Light Studio'ya yeniden yükler; büyük projelerde kısa bir bekleme olabilir.
- `hdrls_probe.py` / `hdrls_probe_looks.py`: sorun olursa Text Editor'de çalıştırın; `HDRLS_Rapor`
  metin bloğu eklentilerin sahneye yazdıklarını, operatörleri ve handler'ları listeler.
