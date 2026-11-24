# BlendHDRi — HDRI Studio for Blender

HDR Light Studio'nun temel iş akışını Blender içine getiren bir eklenti:
softbox, strip, octabox, ring gibi stüdyo ışıklarını bir **HDRI tuvali** üzerine
yerleştirirsiniz, sahne aydınlatması anında güncellenir; modelin üzerine
tıklayarak ışığı yansımanın/aydınlatmanın düşeceği yere konumlandırır, sonucu
32-bit **EXR / HDR** olarak dışa aktarırsınız.

| HDRI tuvali (Product Dark + Octabox) | Aynı HDRI ile Cycles render |
|---|---|
| ![canvas](docs/canvas_product_dark.png) | ![render](docs/render_product_dark.png) |

## Özellikler

- **Studio Editor** – Shader Editor açar gibi ekranı bölerek açılan canlı HDRI
  tuvali (Image Editor tabanlı). Işıklar tuval üzerinde çerçeve ve isimle çizilir.
- **Tuvalde düzenleme** (`Edit on Canvas`)
  - Sol tık: ışığı seç / sürükle
  - `Ctrl` + sol tık: tıklanan yere yeni ışık ekle
  - `Ctrl` + tekerlek: boyut, `Shift` + tekerlek: döndürme, `Alt` + tekerlek: parlaklık
  - `H`: gizle/göster, `X` / `Del`: sil, `Esc` / sağ tık: bitir
- **LightPaint** – 3B görünümde modele tıklayın/sürükleyin; aktif ışık
  - *Reflection*: yansıması tıkladığınız noktada görünecek şekilde,
  - *Illumination*: yüzeyi tam karşıdan aydınlatacak şekilde,
  - *Rim*: yüzeyin arkasından kenar ışığı verecek şekilde yerleşir.
  - `Shift` + tık yeni ışık ekler, `1/2/3` mod değiştirir.
- **Hazır ışıklar**: Large / Square / Small Softbox, Strip, Horizontal Strip,
  Octabox, Round Softbox, Ring Light, Overhead Panel, Hard Spot, Sun, Window,
  Black Flag, Reflector Card.
- **Hazır stüdyo kurulumları**: Three Point, Product White, Product Dark,
  Car Studio, Portrait, Dramatic Rim, Outdoor Sky (aktif kameraya göre yönlenir).
- **Işık parametreleri**: şekil (dikdörtgen / yuvarlak / octabox / ring),
  konum (boylam/enlem), dönüş, açısal genişlik/yükseklik, kenar yumuşaklığı,
  köşe yuvarlaklığı, merkez falloff, lineer gradyan, renk, Kelvin sıcaklığı,
  yoğunluk, opaklık ve karışım modu (Add / Over / Multiply — bayrak ve jel için).
- **Arka plan**: düz renk, gök/ufuk/zemin gradyanı veya mevcut bir HDRI
  görüntüsünün üzerine ışık ekleme.
- **Canlı dünya**: `HDRI Studio World` otomatik oluşturulur; *Preview in Viewport*
  3B görünümü sahne dünyası ile Material Preview'a alır. Önceki dünyaya tek
  tıkla dönülebilir.
- **Gerçek alan ışıkları (Area Light)**: her ışığın çıktısı *HDRI*, *Area Light*
  veya *Both* olabilir. Area ışıkları hedef nesnenin (ya da dünya merkezinin)
  etrafında, seçilen mesafede, HDRI'deki konum/boyut/renk/güçle senkron tutulur
  ("HDRI Studio Lights" koleksiyonu). *Detach Area Lights* ile sıradan sahne
  ışıklarına dönüştürülebilir.
- **Işık dokusu**: bir ışığın içine görüntü (softbox fotoğrafı, pencere, gobo…)
  yerleştirin; alfa kanalı maske olarak kullanılır.
- **Kullanıcı presetleri**: aktif ışığı veya tüm stüdyo kurulumunu kaydedin;
  `+` ve *Studio Setups* menülerinde "My Lights / My Setups" altında her
  dosyada kullanılabilir (Blender config klasöründe `blendhdri/presets.json`).
- **Dışa aktarma**: 1K–8K OpenEXR (32-bit float) veya Radiance HDR;
  isteğe bağlı olarak kaydedilen dosyayı kullanan yeni bir World oluşturma.

## Kurulum

Blender **4.2 veya üstü** (5.x ile test edildi).

1. `blendhdri` klasörünü zip'leyin:
   ```bash
   zip -r blendhdri.zip blendhdri
   ```
2. Blender → *Edit ▸ Preferences ▸ Add-ons* (4.2+: *Get Extensions* sağ üst menü
   ▸ **Install from Disk…**) → `blendhdri.zip` seçin ve etkinleştirin.

## Kullanım

1. 3B görünümde `N` panelini açın → **HDRI Studio** sekmesi →
   **Open Studio Editor** (ya da *Window ▸ HDRI Studio Editor* /
   *View ▸ HDRI Studio Editor*). Henüz ışık yoksa *Three Point* kurulumu yüklenir.
2. **Preview in Viewport** ile 3B görünümde sonucu canlı izleyin
   (Material Preview veya Rendered modu).
3. `+` menüsünden ışık ekleyin ya da **Studio Setups** menüsünden bir kurulum seçin.
4. **Edit on Canvas** ile ışıkları tuvalde sürükleyin veya **LightPaint** ile
   doğrudan modelin üzerine "boyayın".
5. **Export** panelinden çözünürlük ve format seçip HDRI'yi kaydedin.

> Canlı güncelleme hem *Material Preview* (EEVEE) hem *Rendered* (Cycles)
> görünümde çalışır: World iki görüntü arasında dönüşümlü güncellenir, böylece
> Cycles her değişiklikte yeni HDRI'yi yükler.

> Not: Tuval görüntüsü .blend dosyasına kaydedilmez; dosya açıldığında ışık
> ayarlarından otomatik olarak yeniden üretilir. Kalıcı bir dosya için Export
> kullanın.

## Teknik notlar

- HDRI, numpy ile prosedürel olarak rasterize edilir (gnomonik projeksiyon ile
  her ışık küre üzerinde doğru şekilde bükülür). 1K önizleme birkaç ışıkla
  ~50 ms, 4K dışa aktarma < 1 sn sürer.
- Eşleme Blender/Cycles equirectangular konvansiyonunu birebir izler
  (`u = 0.5 - atan2(y, x) / 2π`, `v = 0.5 + asin(z) / π`).

| Dosya | İçerik |
|---|---|
| `blendhdri/render.py` | Saf numpy HDRI motoru, koordinat dönüşümleri, RGBE yazıcı |
| `blendhdri/props.py` | Sahne / ışık özellikleri |
| `blendhdri/studio.py` | Tuval görüntüsü, World node ağacı, canlı güncelleme |
| `blendhdri/presets.py` | Hazır ışıklar ve stüdyo kurulumları |
| `blendhdri/ops.py` | Operatörler (ekle/sil, kurulum, editör açma, dışa aktarma) |
| `blendhdri/canvas.py` | Tuval üstü çizim ve interaktif düzenleme |
| `blendhdri/lightpaint.py` | 3B görünümde tıkla-yerleştir |
| `blendhdri/ui.py` | Paneller, liste, başlık menüleri |
