# Android releases

Android distribution is independent of VPS deployment. The `android-release`
workflow builds tags named `android-v<versionName>` from commits on master and
publishes `aisomedo.apk` plus its SHA-256 checksum through GitHub Releases.
No Play Store account or SSH connection is involved.

## One-time signing setup

Create a dedicated release keystore and store an encrypted offline backup with
its alias and passwords. Keep using the same key: Android cannot install an
update signed by a different key over an existing installation. Never commit
the keystore, passwords, or their base64 representation.

Create the `android-release` GitHub environment; restrict eligible tags to
`android-v*` and restrict who can create release tags. Configure secrets:

- `ANDROID_KEYSTORE_BASE64`: base64 encoding of the binary keystore.
- `ANDROID_KEYSTORE_PASSWORD`: keystore password.
- `ANDROID_KEY_ALIAS`: release-key alias, not the debug alias.
- `ANDROID_KEY_PASSWORD`: private-key password.

Optional environment reviewers can protect release signing. Missing secrets
fail before building; temporary keystores are removed even on failure.

## Kısa kurulum ve yayın rehberi (Windows / PowerShell)

### 1. İmzalama anahtarını oluşturun — yalnız ilk kez

Daha önce release APK dağıttıysanız mevcut anahtarı kullanın. Yeni anahtar,
mevcut kurulumların normal şekilde güncellenmesini engeller.

JDK'nın `keytool` aracını kullanın. Android Studio'nun varsayılan kurulumunda
araç `C:\Program Files\Android\Android Studio\jbr\bin\keytool.exe` konumundadır.
Aşağıdaki komutlarda `keytool` bulunamazsa bu tam yolu `& "..."` ile çalıştırın.

```powershell
$KeyDir = Join-Path $HOME ".android-signing"
New-Item -ItemType Directory -Path $KeyDir -Force | Out-Null
$Keystore = Join-Path $KeyDir "aisomedo-release.jks"
if (Test-Path $Keystore) { throw "Keystore zaten var; mevcut dosyayı kullanın." }

keytool -genkeypair -v -keystore $Keystore -storetype JKS `
    -alias aisomedo-release -keyalg RSA -keysize 3072 -validity 10000
if ($LASTEXITCODE -ne 0) { throw "Keystore oluşturulamadı." }
```

İstendiğinde güçlü bir keystore şifresi belirleyin, sertifika bilgilerini
doldurun ve onaylayın. Sertifika bilgileri APK'da görülebilir. Anahtar şifresi
sorulduğunda **Enter** basarsanız keystore şifresi kullanılır. Şifreleri komut
satırına yazmayın. Keystore'u, alias'ı ve şifreleri güvenle saklayın; şifreli
çevrimdışı yedek alın. Sonraki yayınlarda aynı anahtarı kullanın.

### 2. GitHub secret'larını doldurun

Aynı PowerShell oturumunda keystore'un Base64 içeriğini panoya kopyalayın:

```powershell
[Convert]::ToBase64String([System.IO.File]::ReadAllBytes($Keystore)) | Set-Clipboard
```

GitHub deposunda **Settings → Environments → New environment** yolundan
`android-release` oluşturun. **Environment secrets → Add secret** ile ekleyin:

| Secret | Değer |
| --- | --- |
| `ANDROID_KEYSTORE_BASE64` | Panoya kopyalanan içerik; dosya yolu değil |
| `ANDROID_KEYSTORE_PASSWORD` | Belirlediğiniz keystore şifresi |
| `ANDROID_KEY_ALIAS` | Bu örnekte `aisomedo-release` |
| `ANDROID_KEY_PASSWORD` | Anahtar şifresi; Enter kullandıysanız keystore şifresi |

Değerleri **Variables** değil **Secrets** bölümüne, tırnak eklemeden girin.
Environment'ın izin verilen tag kuralını `android-v*` yapın; mümkünse yayın
onayı ekleyin. Özel depolarda environment desteği GitHub planına bağlıdır.

**Base64 şifreleme değildir.** Çevrimiçi dönüştürücü kullanmayın; keystore,
şifreler veya Base64 içeriğini Git'e eklemeyin. Kaydettikten sonra
`Set-Clipboard -Value ""` ile panoyu ve varsa ilgili pano geçmişini temizleyin.

### 3. Sürümü yayımlayın ve APK'yı indirin

1. `android/app/build.gradle.kts` içinde sonraki yayın için `versionCode`
   artırın ve `versionName` belirleyin. Değişikliği CI geçtikten sonra `master`
   üzerine alın. İlk yayında henüz kullanılmamış mevcut sürüm kullanılabilir.
2. Proje kökünde aşağıdaki komutları çalıştırın. **Tag gönderimi başarılı build
   sonrasında GitHub Release yayımlar; yalnız yerel APK üretmez.**

   ```powershell
   git fetch origin master
   if ($LASTEXITCODE -ne 0) { throw "master alınamadı." }
   $masterSha = git rev-parse origin/master
   if ($LASTEXITCODE -ne 0) { throw "Commit bulunamadı." }
   git show "${masterSha}:android/app/build.gradle.kts" | Select-String 'versionCode|versionName'
   if ($LASTEXITCODE -ne 0) { throw "Sürüm okunamadı." }
   $Surum = Read-Host "Yukarıdaki versionName değerini girin"
   $Etiket = "android-v$Surum"
   git tag -a $Etiket $masterSha -m "Android $Surum"
   if ($LASTEXITCODE -ne 0) { throw "Tag oluşturulamadı; mevcut tag'i değiştirmeyin." }
   git push origin $Etiket
   if ($LASTEXITCODE -ne 0) { throw "Tag gönderilemedi." }
   ```

3. **Actions → android-release** koşusunu takip edin; gerekiyorsa onaylayın.
   Workflow test, lint ve imza kontrolünü yapar. Bilgisayarınıza Android SDK
   kurmanız gerekmez; Google Play hesabı da gerekmez.
4. **Releases → ilgili sürüm → Assets** altında `aisomedo.apk` ve
   `aisomedo.apk.sha256` dosyalarını indirin. `Get-FileHash .\aisomedo.apk
   -Algorithm SHA256` çıktısını checksum dosyasındaki değerle karşılaştırın.
5. APK'yı telefonda açın; gerekirse indirme kaynağına uygulama yükleme izni
   verin. Debug sürümüyle imza uyuşmazlığı olabilir. Eski uygulamayı kaldırmak
   yerel verileri siler; verileri korumadan kaldırmayın.

İlk iki adım tek seferliktir; sonraki yayınlarda yalnız sürüm/yayın adımlarını
tekrarlayın. Backend güncelleme ayarları ve indirme adresi aşağıdadır.

Kaynaklar: [Android imzalama rehberi](https://developer.android.com/studio/publish/app-signing),
[keytool belgeleri](https://docs.oracle.com/en/java/javase/25/docs/specs/man/keytool.html).

## Release procedure

1. Increase `versionCode` in `android/app/build.gradle.kts` for every release;
   choose `versionName` and merge the version update to master after CI passes.
2. Create/push matching `android-v<versionName>` tag on that master commit.
3. Verify workflow success and the APK/checksum attached to the Release.
4. Set production `ANDROID_CURRENT_VERSION_CODE` to the distributed code and
   `ANDROID_UPDATE_URL` to the release APK. Empty `ANDROID_MIN_VERSION_CODE`
   preserves the backend's N/N-1 policy. Backend deploys do not bump these values.

The workflow runs release unit tests/lint, validates the APK signature with
`apksigner`, rejects a debug certificate, and uploads into a draft Release
before publishing it. It never overwrites a published release. If publication
fails midway, inspect and remove only the incomplete draft before rerunning.

The stable URL is `https://github.com/OWNER/REPO/releases/latest/download/aisomedo.apk`.
Private repositories require download authentication; use a public repository
or another operator-managed HTTPS distribution endpoint if administrators must
download without GitHub credentials. Never make repository/package visibility
public automatically.
