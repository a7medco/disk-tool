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

## Microsoft Safety Scanner في الـ WinPE (تجربة ناجحة)

`msert.exe` (Microsoft Safety Scanner، أداة رسمية مجانية من مايكروسوفت) متحطوطة على كل WinPE ISO بتتبني، بتتنزل fresh في كل build (عشان تنتهي صلاحيتها بعد 10 أيام). مكانها جوه الصورة: `Windows\System32\Tools\msert.exe`.

- **جرّبناها فعلياً** على WinPE حقيقي: فتحت الـ wizard كامل، وعملت Full scan حقيقي شمل الديسكات التانية (مش بس X:).
- **استخدم "Full scan"، مش "Customized scan".** زرار "Choose Folder..." (اللي بيختار فولدر معيّن) مش شغال في WinPE (محتاج مكوّنات shell إضافية). لكن **"Full scan" بيفحص كل الـ "Local Fixed Disk" تلقائياً من غيره** — جرّبناها وشافت ديسك تاني (C:) وكمّلت تفحص فيه من غير أي تدخّل.
- يعني لو الفلاشة/الهارد المصاب ظاهر كـ Local Fixed Disk جوه WinPE (أغلب الحالات)، Full scan هيوصله لوحده.

## أدوات محمولة جوه الـ WinPE (Tools\)

كل WinPE ISO فيها فولدر `Tools\` على الـ media نفسها (مش جوه boot.wim، عشان ما تاخدش رامات زيادة). الأدوات دي **نسخ محمولة من توزيعة Sergei Strelec WinPE** (توزيعة طرف تالت مشهورة)، **مش من موقع كل أداة الرسمي** — يعني الرخصة الأصلية لكل أداة لسه سارية (أغلبها freeware)، بس التوزيع ده مش من المطوّر الأصلي مباشرة.

| الفولدر/الملف | الأداة | الاستخدام |
|---|---|---|
| `Tools\x64\EasyBCD_*.exe`, `x86\EasyBCD_*.exe` | EasyBCD | تعديل/إصلاح bootloader (BCD) |
| `Tools\x64\RecoverKeys_x64.exe`, `x86\RecoverKeys_x86.exe` | Recover Keys | استرجاع مفاتيح تفعيل البرامج |
| `Tools\x64\ShowKeyPlus_x64.exe` | ShowKeyPlus | قراءة مفتاح تفعيل ويندوز من الـ BIOS/الريجستري |
| `Tools\x64\TotalCommander_x64_Eng.exe`, `x86\TotalCommander_x86_Eng.exe` | Total Commander | file explorer ثنائي اللوحة |
| `Tools\x86\WinNTSetup_x86.exe` | WinNTSetup | تسطيب ويندوز متقدم (WIM/ESD) |
| `Tools\AnyDesk_All.exe` | AnyDesk | دعم عن بُعد |
| `Tools\CrystalDiskInfo_All.exe` | CrystalDiskInfo | حالة SMART للهارد |
| `Tools\CrystalDiskMark_All.exe` | CrystalDiskMark | قياس سرعة الهارد |
| `Tools\cpuz_All.exe` | CPU-Z | معلومات المعالج/الرامات |
| `Tools\Defraggler_All_Eng.exe` | Defraggler | Defragmentation |
| `Tools\DiskpartGUI_All.exe` | DiskpartGUI | واجهة رسومية لـ diskpart |
| `Tools\DismPlus_All.exe` | DISM++ | تنظيف وإدارة صور ويندوز |
| `Tools\DoubleDriver_All.exe` | Double Driver | نسخ احتياطي/استرجاع درايفرات |
| `Tools\HWiNFO_All.exe` | HWiNFO | معلومات الهاردوير بالتفصيل |
| `Tools\keyboardtestutility_All.exe` | Keyboard Test Utility | اختبار الكيبورد |
| `Tools\MonitorTest_All.exe` | MonitorTest | اختبار الشاشة |
| `Tools\OemKey_All.exe` | OEM Key Tool | قراءة مفتاح الـ OEM |
| `Tools\SoundCheck_All.exe` | SoundCheck | اختبار الصوت |
| `Tools\TeraCopy_All.exe` | TeraCopy | نسخ ملفات بإعادة محاولة واستئناف |
| `Tools\x64\BootSectGui-x64.exe` | BootSectGUI | إصلاح/كتابة boot sector (MBR) — ✅ جُرِّب فعلياً على WinPE حقيقي، فتح وشغال بالكامل |
| `Tools\x64\BCDBootGUI-x64.exe` | BCDBootGUI | واجهة رسومية لـ bcdboot (إعادة بناء BCD) — ✅ جُرِّب فعلياً، فتح وشغال بالكامل |
| `Tools\x64\HDDLowLevelFormatTool_x64.exe` | HDD Low Level Format Tool | فورمات منخفض المستوى للهارد/الفلاشة — ❌ جُرِّب فعلياً بالـ exe الحقيقي (LLFTOOL.exe، 64-bit، .NET) بعد استبدال غلاف الـ SFX: بيتنفّذ ويرجع للبرومبت فورًا من غير أي نافذة ومن غير أي خطأ (حتى SxS)؛ الملف يحتاج .NET Framework كامل (CLR) وده مش متوفر في WinPE رغم وجود Microsoft.NET\\Framework64\\v4.0.30319 الجزئي؛ الأداة دي على الأرجح مش هتشتغل في WinPE من غير إضافة مكونات .NET إضافية |

ملاحظة: TeraCopy في الأصل بيتكامل مع قائمة الكليك اليمين بتاعة Explorer، ودي مش متاحة في WinPE البسيطة — تشغّله من ملفه مباشرة بدل كده.

### ⚠️ حالة الأدوات: اللي 64-بت شغالة، اللي 32-بت لسه لأ (قيد الإصلاح)

جرّبنا فعلياً على WinPE حقيقي وفحصنا الـ manifest المدمج في كل exe (`strings`). النتيجة مختلطة:

- **✅ Total Commander x64 اتفتح وشغال 100%** (الواجهة الكاملة، التصفح، كل حاجة). ده لأن الـ manifest بتاعه بيطلب نسخة Common Controls **64-bit (amd64)**، والمكوّن ده موجود أصلاً في WinPE + نسخناه إحنا كمان — خلاص اتحل.
- **❌ TeraCopy وCrystalDiskInfo وKeyboard Test Utility وCPU-Z وHWiNFO** (وكل الأدوات التانية الـ 32-بت) **لسه بتفشل** بنفس الخطأ: "the application has failed to start because its side-by-side configuration is incorrect". السبب: الأدوات دي manifestها بيطلب نسخة Common Controls **32-bit (X86, عشان WOW64)**. نسخنا المكوّن ده فعلياً (تأكدنا: الفولدر والـ manifest والـ DLL الحقيقي كلهم وصلوا صح لجوه WinSxS، شفناهم بعين)، **ومع ذلك برضه بيفشل** — يبقى المشكلة مش نقص ملفات، حاجة تانية أعمق في إزاي WOW64 بالذات بيتعامل مع الطلب ده (يمكن محتاج الإصدار الحرفي `6.0.0.0` نفسه، مش أي إصدار تاني، وده مش موجود في ويندوز الحديث خالص).

**يعني:** لو الأداة x64 (زي Total Commander) — هتفتح أكيد. لو 32-بت — هتبقى موجودة في الـ ISO بس مش هتفتح لحد ما نلاقي حل أعمق للـ WOW64.

**Microsoft Safety Scanner (`msert.exe`) مش متأثر** بالمشكلة دي خالص — مجرّب وشغال 100% (شوف القسم اللي فوق).
