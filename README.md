# Windows Disk Tool

نسخة ويندوز من أداة الأقراص، بواجهة رسومية راقية.

## ملف exe واحد لصحابك (من غير بايثون)

على جهازك الويندوز (اللي عليه بايثون) دبل كليك على:

```
build.bat
```

بيطلّع `dist\DiskTool.exe` + فولدر `dist\bin`.
ابعت فولدر dist كله. صاحبك يدوس دبل كليك على DiskTool.exe، يطلب صلاحية الأدمن لوحده ويشتغل.
ملف الإعدادات وفولدر Ventoy بيتحطوا جنب الـ exe.

جاهز جوه النسخة 2.2:
- `bin\ventoy\ventoy-1.1.18` — للـ Multi-ISO.
- `bin\yumi\YUMI-exFAT-1.0.4.3.exe` — صفحة YUMI exFAT (منفصلة عن Ventoy).
- `redist\MicrosoftEdgeWebview2Setup.exe` جوه الـ exe — لو الجهاز مفيهوش WebView2 بيسطبه لوحده (محتاج نت)، ولو فشل بيفتح الواجهة البسيطة.

## التشغيل من الكود (الواجهة الحلوة) — لازم Administrator

```
pip install pywebview
python app.py
```

الواجهة دي صفحة ويب جوه نافذة ويندوز، بترسمها Edge WebView2 اللي أصلاً موجودة في ويندوز 10 و 11، فمحتاجش أي حاجة تانية غير pywebview مرة واحدة.

## نسخة احتياطية من غير أي تسطيب

```
python gui.py
```

دي بـ Tkinter اللي بييجي مع بايثون، لو حبيت تشغّل من غير pywebview.

## صدقة جارية

الأداة دي صدقة جارية على روح زينب عبد العليم مصطفى، رحمها الله.

## الوظائف

- الهيكل: واجهة app.py (pywebview)، ورفع صلاحية الأدمن، وواجهة احتياطية gui.py.
- طبقة أوامر: PowerShell و diskpart، مع قراءة مخرجات JSON.
- عرض الأقراص والصحة (SMART) — `Get-Disk` + `Get-PhysicalDisk`.
- حماية: قرص الإقلاع مخفي عن عمليات المسح.

## الإصدار 2.0 — كل الوظائف في الواجهة (app.py)

| القسم | الوظيفة | الأمر |
|------|---------|-------|
| Drives | الأقراص والصحة | Get-Disk + Get-PhysicalDisk |
| Drives | فورمات قرص كامل | diskpart |
| Drives | فورمات بارتيشن / إخراج | Format-Volume / Shell Eject |
| Drives | HDD repair: عدادات SMART | Get-StorageReliabilityCounter |
| Drives | HDD repair: فحص سطح القرص (قراءة فقط) | قراءة PhysicalDrive بلوك بلوك |
| Drives | HDD repair: إصلاح ملفات | chkdsk /scan /f /r |
| Drives | HDD repair: ملفات ويندوز | DISM /RestoreHealth + sfc /scannow |
| Drives | نسخ سريع | robocopy |
| Bootable | فلاشة ويندوز | diskpart + robocopy + DISM /Split-Image |
| MultiBootable ISO Create | Ventoy | Ventoy2Disk.exe VTOYCLI /I أو /U |
| MultiBootable ISO Create | YUMI exFAT | بيفتح YUMI في نافذته |
| Bootable | كتابة IMG خام | PhysicalDrive |
| Hardware checks | اختبار الرامات + آخر نتيجة | bcdedit {memdiag} + سجل MemoryDiagnostics-Results |
| Windows | برامج بدء التشغيل | StartupApproved (نفس Task Manager) |
| Windows | نسخ/استرجاع التعريفات | dism /export-driver + pnputil /add-driver |
| Windows | باسوورد حساب محلي | net user |

## Ventoy للـ Multi-ISO

نزّل نسخة ويندوز من ventoy.net وفكّها جوه `bin\ventoy`، أو اختار مكانها من زرار Locate.

## الأمان

أي عملية بتمسح أو بتغيّر بيانات لازم تتأكد مرتين: في الواجهة، وبعدها `core/guard.py` بيراجع من الأول قبل التنفيذ. بيرفض هارد الويندوز، وهارد الإقلاع، والهارد اللي البرنامج شغال منه. تفاصيل الحماية في أول الملف.

## التشغيل على WinPE (من 2.10.0)

البرنامج بيعرف لوحده إنه شغال على WinPE، وساعتها بيفتح الواجهة البسيطة. بيقرا الهاردات من غير PowerShell، ويستخدم diskpart وdism.

- الصفحات: Disks وFormat وchkdsk وFast copy وInstall Windows. في Install Windows بتختار `install.wim` أو `install.esd`، لأن فتح الـ ISO محتاج PowerShell.
- على WinPE البرنامج **مش بيمسح أبداً** أي هارد عليه ويندوز (فولدر Windows أو EFI أو Recovery)، ولا فلاشة Ventoy، ولا الهارد اللي البرنامج شغال منه.
- استخدم `DiskTool.zip` (نسخة الفولدر). نسخة الـ exe الواحد بتفك نفسها على `X:` وده مساحته صغيرة.
- لو `robocopy` مش موجود، النسخ بيتم بالناسخ الداخلي. ولو `dism` مش موجود، التسطيب بيتم بـ `bin\wimlib`.

## WinPE بتاعنا (من v2.10.0 - المرحلة 2)

كل build على GitHub Actions بيطلع كمان `WinPE_amd64.iso` جنب إصدار DiskTool، مبني بأدوات مايكروسوفت الرسمية (Windows ADK + WinPE add-on، `copype` + DISM). فيه PowerShell والـ Storage والشبكة (الشبكة السلكية بتشتغل لوحدها - `wpeinit` بيتنادي تلقائي من `startnet.cmd`).

- أحدث نسخة: https://github.com/a7medco/disk-tool/releases/download/latest/WinPE_amd64.iso
- حطها في Ventoy وبوت منها زي أي ISO.
- لسه من غير DiskTool جواها (ده في المرحلة 3). دلوقتي هي WinPE بتاعتنا بس، بديل لـ Windows Setup's WinPE اللي استخدمناه في المرحلة 1.
