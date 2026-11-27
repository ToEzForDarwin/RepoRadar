# Repo Radar

Ekranın sağında duran küçük bir pencere. GitHub'daki en iyi repoları konu başlıklarına göre gösterir. Her 6 saatte bir kendini günceller ve bir listeye yeni repo girince Windows bildirimi gönderir.

## Gerekenler
- Python 3. Yoksa terminalde: `winget install -e --id Python.Python.3.12 --scope user` (yönetici izni istemez). Ek paket gerekmez.
- Microsoft Edge (Windows'ta hazır gelir). Pencere Edge'in "uygulama modu"yla açılır.

## Kurulum
1. `repo-radar.zip` dosyasını istediğin bir klasöre çıkar, örneğin `C:\Users\<sen>\RepoRadar`.
2. `Baslat.bat` dosyasına çift tıkla. Sağda dar bir pencere açılır.
3. İlk güncelleme **2-3 dakika** sürer (GitHub şifresiz kullanımda dakikada 10 aramaya izin veriyor). Pencerede "Güncelleniyor..." yazar.
4. Windows açılınca kendiliğinden başlasın istersen bir kez `Baslangica_ekle.bat` çalıştır.

Sağ alttaki bildirim alanında mavi bir radar simgesi çıkar. Tıklayınca pencere açılır; sağ tıkta **Şimdi yenile** ve **Çıkış** var. Pencereyi kapatsan da program simgede çalışmaya devam eder. Simge gizli simgeler (^) içinde kalırsa sürükleyip görev çubuğuna bırakabilirsin.

İlk açılışta simge için `pystray` ve `pillow` paketleri otomatik kurulur (internet gerekir).

## Sekmeler
- **Projelerim**: her projenin GitHub reposundan **canlı** durum (son commit, son build sonucu, açık issue/PR, milestone ilerlemesi). 2 dakikada bir yenilenir; build bitince bildirim gelir. Durum, ilerleme ve sıradaki adımı karttaki "düzenle" ile değiştirirsin. Yeni proje eklemek için `projects.json`.
- **Proje notları**: her proje kartında son 5 not ve not yazma kutusu (Ctrl+Enter). Notlar reponda "📝 Proje notları" adlı tek bir issue'ya yorum olarak kaydedilir; ilk notta issue kendiliğinden açılır. Telefondaki GitHub uygulamasından da okuyup yazabilirsin. Yazmak için token'da Issues izni "Read and write" olmalı (diğer izinler Read-only kalabilir). Bu issue açık issue sayısına dahil edilmez.
- **Benim repolarım**: GitHub hesabını bağlarsan gizliler dahil kendi repoların. Fine-grained token: Actions, Contents, Pull requests için Read-only, proje notu yazacaksan Issues için Read and write; token `data/token.txt` içinde sadece bu bilgisayarda durur.

## Ayarlar (`categories.json`)
- `refresh_hours`: kaç saatte bir güncellensin (varsayılan 6).
- `top_n`: her kategoride kaç repo (varsayılan 20).
- `widget_width`: pencere genişliği.
- `categories`: kategori ekle veya çıkar. Her sorgu GitHub arama dilinde, örneğin `topic:flutter`.
- `github_token`: isteğe bağlı. Boş da çalışır; token koyarsan güncelleme 3 kat hızlanır.

## Neyi gösterir, neyi göstermez
- Yıldız, 7 günlük yıldız artışı, lisans, son güncelleme ve açıklama canlıdır.
- Kartlardaki renkli işaretler (Aktif, Durgun, Lisans yok, Hızlı yükseliyor) otomatik kurallardır, insan yorumu değildir.
- Elle yazılmış dürüst yorumlar sadece 3D repolarında var (`notes.json`). Başka repolara da not ekleyebilirsin.
- 7 günlük artış, program birkaç gün çalıştıktan sonra dolmaya başlar.
- Kategoriler GitHub "topic" etiketlerine göre çalışır. Etiketi olmayan iyi bir repo listede çıkmayabilir.

## İş bilgisayarında
Program sadece `api.github.com` adresine bağlanır ve sadece kendi klasörüne yazar. Yönetici izni istemez. Yine de şirket kuralları Python çalıştırmayı veya Başlangıç klasörünü kısıtlıyorsa çalışmayabilir.
