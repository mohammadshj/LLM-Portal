# LLM Portal

پورتال فارسی برای گفت‌وگو و مقایسهٔ هم‌زمان حداکثر سه مدل زبانی است. رابط React به‌صورت فایل استاتیک از Nginx ارائه می‌شود و Django تاریخچه و مصرف هر کاربر را در PostgreSQL نگه می‌دارد.

- پاسخ جریانی، زمان پاسخ و تنظیمات استدلال مستقل برای هر مدل
- گفت‌وگوهای هم‌زمان، توقف مستقل هر مدل، ویرایش و تولید مجدد نسخه‌دار، سنجاق و خروجی Markdown
- نمایش فرمول، ثبت بازخورد و گزارش شخصی اعتبار و مصرف
- کشف مدل از اتصال‌های مستقل، تعیین تعرفهٔ فروش و مدیریت اعتبار تومانی در Django Admin

## راه‌اندازی سریع

به Docker و افزونهٔ Docker Compose نیاز دارید. برای نصب تازه، از ریشهٔ مخزن فایل تنظیمات را بسازید. برای نصب موجود [راهنمای ارتقا](docs/billing.md#upgrade) را بخوانید.

```sh
cp .env.example .env
chmod 600 .env
```

در `.env` برای `DJANGO_SECRET_KEY` و `POSTGRES_PASSWORD` دو مقدار تصادفی مستقل بگذارید. برای آزمایش محلی روی HTTP، `DJANGO_DEBUG=true` تنظیم کنید. در استقرار سازمانی، `DJANGO_DEBUG=false`، دامنهٔ واقعی در `DJANGO_ALLOWED_HOSTS`، مبدأ HTTPS در `CSRF_TRUSTED_ORIGINS` و پراکسی میزبان با TLS معتبر لازم است.

```sh
docker compose build
docker compose up -d db
docker compose run --rm backend python manage.py migrate
docker compose run --rm backend python manage.py collectstatic --noinput
docker compose run --rm backend python manage.py createsuperuser
docker compose run --rm backend python manage.py seed_demo
docker compose up -d
curl --fail http://127.0.0.1:8080/api/health/
```

دستور اختیاری `seed_demo` دو مدل رایگان برای آزمایش آفلاین می‌سازد. در `http://127.0.0.1:8080/` با حساب ساخته‌شده وارد شوید، «گفتگوی تازه» را باز کنید، یک مدل نمایشی انتخاب کنید و یک سؤال بفرستید.

## اتصال اولین مدل واقعی

۱. کلید سرویس را در `.env` در متغیری مانند `LLM_GATEWAY_API_KEY` قرار دهید و `docker compose up -d --force-recreate backend` را اجرا کنید.

۲. در `/admin/` یک «اتصال سرویس مدل» بسازید. نوع سرویس، Base URL و **نام متغیر کلید** را وارد کنید. اتصال را ذخیره و **Sync Models** را اجرا کنید. برای سرویس فاقد فهرست مدل، یک مدل با شناسهٔ دقیق آن و همین اتصال ثبت کنید.

۳. در صفحهٔ مدل، ظرفیت ورودی و سقف خروجی را بررسی کنید، هر دو تعرفهٔ ورودی و خروجی را به تومان برای یک میلیون توکن تعیین و مدل را فعال کنید. صفر به معنی رایگان است. برای مدل پولی، در صفحهٔ کاربر از «تغییر اعتبار» موجودی کافی تخصیص دهید. پس از بارگذاری دوبارهٔ پورتال، مدل را از انتخابگر گفتگو انتخاب کنید.

## اجرای تست‌ها

تست‌های Django را روی نصب آزمایشی Compose اجرا کنید. برای تست واحد و ساخت فرانت‌اند روی میزبان، Node.js 24 و npm لازم است.

```sh
docker compose run --rm backend python manage.py test portal
(cd frontend && npm ci && node --test tests/*.mjs && npm run build)
```

## راهنماها

- [مدیریت کاربران، اعتبار و گزارش مالی](docs/billing.md) · [ارتقا و پشتیبان‌گیری](docs/billing.md#upgrade)
- [کشف مدل‌ها و تنظیم اتصال](docs/discovery.md) · [تنظیم Thinking](docs/thinking.md)
- [گفتگو، Streaming و ویرایش پیام‌ها](docs/streaming.md)
- [معماری، API، توسعهٔ محلی، لوگو، فونت و تم](docs/architecture.md)
- [آزمون چندمدلی در مرورگر](tests/browser/README.md) · [سوابق اعتبارسنجی](docs/validation.md)
