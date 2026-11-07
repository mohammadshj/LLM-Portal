# LLM Portal — پورتال مدل‌های زبانی

نسخهٔ اولیهٔ اختصاصی با Python 3.12، Django 5.2 LTS، DRF، PostgreSQL 17 و React 19 / TypeScript / Vite. رابط فارسی، RTL و واکنش‌گراست. Frontend در زمان ساخت به فایل استاتیک تبدیل می‌شود؛ محیط استقرار هیچ پردازش Node.js ندارد.

راهنمای تکمیلی: [تصمیم‌های معماری و API](docs/architecture.md) · [نتایج آزمون‌ها](docs/validation.md)

## قابلیت‌های فعلی

- ورود کاربران ایجادشده توسط مدیر، نشست Django، CSRF و خروج؛ ثبت‌نام عمومی نداریم.
- انتخاب حداکثر سه مدل، ارسال پرسش مشترک و نمایش پاسخ‌های نام‌گذاری‌شده؛ هر مدل در ادامه فقط پاسخ‌های قبلی خودش را می‌بیند.
- تاریخچهٔ اختصاصی هر کاربر، ایجاد و حذف گفتگو، صفحه‌بندی تاریخچه.
- سهمیهٔ تجمعی توکن با تنظیم مدیر، بررسی پیش از فراخوانی و ثبت مصرف گزارش‌شده توسط API. مصرف هزینهٔ دلاری نیست.
- Django Admin برای کاربر، مدل و سهمیه؛ صفحهٔ گزارش مصرف مخصوص مدیر.
- حذف دوره‌ای گفتگوهای قدیمی‌تر از ۳۰ روز؛ شمارنده‌های مصرف با حذف تاریخچه حفظ می‌شوند.
- دو مدل **نمایشی** بدون اینترنت برای آزمون؛ آداپتور Chat Completions سازگار با OpenAI برای اتصال واقعی.

این نسخه تحویل نهایی تمام تعهدات دو PDF نیست. اتصال واقعی به دو ارائه‌دهنده، استقرار یک مدل پزشکی، پژوهش و بنچمارک‌ها، گزارش رویدادهای امنیتی و سخت‌سازی نهایی هنوز انجام نشده‌اند. سندهای ضمیمه منبع نیازمندی هستند؛ زمان‌بندی، قرارداد و تخصیص نیروی انسانی آن‌ها دستور اجرایی پروژه محسوب نمی‌شوند.

## اجرای Docker

از ریشهٔ مخزن:

```sh
cp .env.example .env
# .env را ویرایش کنید؛ دو مقدار مستقل و تصادفی برای SECRET_KEY و PASSWORD قرار دهید.
# برای توسعهٔ HTTP محلی: DJANGO_DEBUG=true
# برای تولید: DJANGO_DEBUG=false و دامنه‌ها و CSRF_TRUSTED_ORIGINS واقعی
chmod 600 .env
docker compose build
docker compose up -d db
docker compose run --rm backend python manage.py migrate
docker compose run --rm backend python manage.py collectstatic --noinput
docker compose run --rm backend python manage.py createsuperuser
# اختیاری، فقط برای آزمایش:
docker compose run --rm backend python manage.py seed_demo
docker compose up -d
```

پورت داخلی وب 8080 است و تنها به loopback سرور متصل است. سرویس Backend و PostgreSQL پورت عمومی ندارند. برای استفاده روی سرور لینوکسی، یک reverse proxy میزبان با TLS معتبر را مقابل پورت 8080 قرار دهید و Host و Origin واقعی را حفظ کنید. تا تنظیم HTTPS از کوکی امن در حالت تولید انتظار ورود روی HTTP نداشته باشید. پروژه گواهی TLS ساختگی تولید نمی‌کند.

کنترل سلامت و تست‌ها:

```sh
curl --fail http://127.0.0.1:8080/api/health/
docker compose exec backend python manage.py test portal
docker compose exec web nginx -t
```

`health` اتصال پایگاه داده را بررسی می‌کند. در محیط‌های دارای TLS inspection، Dockerfileها secret اختیاری BuildKit به نام `proxy_ca` را می‌پذیرند؛ CA باید از محیط معتبر به build داده شود. تأیید TLS را غیرفعال نکنید.

ساخت image، اجرای migration و collectstatic عمداً جدا هستند؛ روی هر راه‌اندازی مهاجرت پایگاه داده انجام نمی‌دهیم. پس از تغییر سورس `docker compose build` و `docker compose up -d` را اجرا کنید. از volume پایگاه داده نسخهٔ پشتیبان بگیرید؛ `down -v` داده‌ها را حذف می‌کند.

## توسعه بدون ساخت مکرر image

یک PostgreSQL محلی یا سرویس PostgreSQL در دسترس لازم است. برای دسترسی از میزبان به DB همین Compose، با یک override محلی پورت `127.0.0.1:5432:5432` را فقط برای سرویس db باز کنید.

```sh
python3.12 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
# متغیرهای .env را در ترمینال توسعه export کنید؛ Django خودکار .env را نمی‌خواند.
# POSTGRES_HOST=127.0.0.1 و DJANGO_DEBUG=true
.venv/bin/python backend/manage.py migrate
.venv/bin/python backend/manage.py runserver 127.0.0.1:8000
# ترمینال دوم:
cd frontend
npm ci
npm run dev
```

Vite درخواست‌های `/api/`، `/admin/` و `/static/` را به Django هدایت می‌کند. CORS و JWT لازم نیست چون مرورگر با یک origin کار می‌کند. در محیط‌هایی که home قابل نوشتن نیست، `npm ci --cache /tmp/portal-npm-cache` به کار ببرید.

برای بررسی سریع مستقل از PostgreSQL، فقط در توسعه و تست می‌توان `PORTAL_SQLITE_TEST=1` داد. SQLite قفل ردیفی PostgreSQL را ندارد و برای اجرای چندکاربره مناسب نیست.

```sh
DJANGO_SECRET_KEY=local-test-only PORTAL_SQLITE_TEST=1 .venv/bin/python backend/manage.py test portal
cd frontend && npm run build
```

## مدیریت مدل و سهمیه

کاربرها را در `/admin/` بسازید. Account در اولین مراجعه ساخته می‌شود؛ برای تعیین سهمیه پیش از اولین ورود، Account را مستقیماً در Admin ایجاد کنید. `token_limit` سقف تجمعی است؛ برای تمدید اعتبار آن را افزایش دهید. بازنشانی خودکار ماهانه یا پرداخت آنلاین نداریم.

برای مدل واقعی در Admin یک LanguageModel با provider برابر `openai`، شناسهٔ دقیق مدل، context window و سقف خروجی تأییدشده توسط ارائه‌دهنده اضافه کنید. `LLM_BASE_URL` (شامل `/v1`) و `LLM_API_KEY` تنها در محیط Backend تنظیم می‌شوند؛ سپس Backend را recreate کنید. کلید هرگز به React، API فهرست مدل‌ها یا مخزن فرستاده نمی‌شود. این نسخه یک endpoint/credential مشترک برای مدل‌های واقعی دارد؛ برای ارائه‌دهندهٔ دوم با قرارداد متفاوت آداپتور و تنظیمات مستقل اضافه شود. تنها مدل‌های Chat Completions با `max_tokens` و `usage.prompt_tokens/completion_tokens` پشتیبانی می‌شوند؛ همهٔ APIهای مدل‌ها سازگار نیستند.

## ساختار و منطق

- `backend/config/`: تنظیمات محیط، URL و WSGI؛ PostgreSQL حالت پیش‌فرض.
- `backend/portal/models.py`: جداول Account، LanguageModel، Conversation، Message و ModelUsage.
- `serializers.py`: قرارداد JSON و اعتبارسنجی ورودی.
- `views.py`: نشست، کنترل دسترسی و مسیرهای REST.
- `services.py`: قوانین گفتگو، سهمیه و شاخه‌های مقایسه. تغییر قواعد کسب‌وکار عمدتاً اینجاست.
- `providers.py`: تنها محل ارتباط با مدل؛ اضافه‌کردن ارائه‌دهنده در این مرز انجام می‌شود.
- `frontend/src/api.ts`: فراخوانی REST و CSRF؛ `main.tsx`: وضعیت صفحه و اجزای رابط؛ `style.css`: چیدمان RTL و موبایل.
- `deploy/`: ساخت استاتیک Frontend و تنظیم Nginx؛ `compose.yaml`: چهار سرویس db، backend، web و cleanup.

جریان درخواست: React ← REST/Session → view → service → provider. ORM تاریخچه و مصرف را در PostgreSQL نگه می‌دارد. متن پاسخ به‌عنوان متن ساده رندر می‌شود، نه HTML مدل؛ برای Markdown هنوز وابستگی اضافه نشده است. Router، state manager، Redis و صف کار در این مرحله لازم نیستند.

## محدودیت‌های نسخهٔ اولیه

قبل از ارسال، تعداد بایت UTF-8 محتوا به‌اضافهٔ حاشیهٔ پیام و حداکثر خروجی رزرو می‌شود. این تخمین برای tokenizerهای byte-BPE محافظه‌کارانه است و ممکن است زودتر از ظرفیت واقعی گفتگو را متوقف کند؛ شمارش دقیق و مدل‌محور هنوز پیاده نشده است. مصرف نهایی واقعی از usage API می‌آید؛ مدل نمایشی از تعداد بایت استفاده می‌کند. قبل از افزودن مدل جدید، tokenizer، قالب پیام و قرارداد usage آن باید اعتبارسنجی شود.

برای سادگی، قفل ردیف Account تا پایان تماس‌های محدودشده با provider نگه داشته می‌شود. پاسخ‌های چند مدل به‌ترتیب دریافت می‌شوند؛ streaming و پردازش موازی نداریم. این انتخاب برای شروع کم‌ترافیک است؛ با افزایش بار، رزرو اعتبار و فراخوانی خارج تراکنش جایگزین شود. اگر فرایند پس از هزینه‌کرد ارائه‌دهنده و پیش از commit قطع شود، مصرف محلی ممکن است با صورتحساب متفاوت شود؛ تطبیق صورتحساب و idempotency سراسری هنوز لازم است. خطای یک مدل مانع ثبت موفقیت مدل‌های دیگر نمی‌شود. ارسال مجدد پس از خطا یک درخواست تازه است.

cleanup هر ۲۴ ساعت اجرا می‌شود؛ گفتگو پس از ۳۰ روز بلافاصله از API مخفی و حداکثر در اجرای بعدی حذف می‌شود. پاک‌سازی backupها سیاست مستقلی می‌خواهد. محدودسازی ورود در Nginx بر مبنای IP برقرار است؛ اگر proxy دیگری جلو آن باشد، برای تشخیص IP واقعی باید trust آن صریحاً تنظیم شود. احراز هویت دومرحله‌ای، audit اختصاصی ورود، قفل حساب و استقرار TLS باید پیش از بهره‌برداری عمومی تکمیل و بازبینی شوند. این سامانه در وضعیت فعلی برای تصمیم‌گیری پزشکی اعتبارسنجی نشده است.
