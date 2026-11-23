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
- `bin\veracrypt` — VeraCrypt 1.26.31 Portable، بيشتغل لو مش متسطب.
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

- الهيكل: قائمة تلقائية من فولدر actions، ورفع صلاحية الأدمن، وتلوين.
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
| Bootable | فلاشة Multi-ISO | Ventoy2Disk.exe VTOYCLI /I أو /U |
| Bootable | كتابة IMG خام | PhysicalDrive |
| Windows | اختبار الرامات + آخر نتيجة | bcdedit {memdiag} + سجل MemoryDiagnostics-Results |
| Windows | برامج بدء التشغيل | StartupApproved (نفس Task Manager) |
| Windows | نسخ/استرجاع التعريفات | dism /export-driver + pnputil /add-driver |
| Windows | أقفال الجهاز | BitLocker + dsregcmd + Secure Boot |
| Windows | باسوورد حساب محلي | net user |
| Windows | تشفير | VeraCrypt |
| Windows | كليك يمين على الدرايف | HKCU\Software\Classes\Drive\shell |

## Ventoy للـ Multi-ISO

نزّل نسخة ويندوز من ventoy.net وفكّها جوه `bin\ventoy`، أو اختار مكانها من زرار Locate.

## إضافة وظيفة جديدة

انسخ `actions\_template.py` باسم جديد، غيّر ORDER و TITLE، واكتب الكود في run_action().


