# کشف مدل و شناسایی قابلیت‌ها

## اولین همگام‌سازی

۱. در محیط Backend مقدار کلید را در متغیری مانند `LLM_GATEWAY_API_KEY` قرار دهید. پس از تغییر محیط، کانتینر Backend را دوباره ایجاد کنید. در Django Admin فقط **نام متغیر** را وارد کنید. برای سرویس بدون احراز هویت می‌توان این فیلد را خالی گذاشت.

۲. در «اتصال‌های سرویس مدل»، یک اتصال فعال بسازید. Base URL همان پایهٔ API سازگار با Chat Completions است، مثلاً `https://gateway.example/v1`. نوع کشف را مطابق سرویس انتخاب کنید.

| نوع اتصال | فهرست مورد استفاده | اطلاعات قابل استخراج |
| --- | --- | --- |
| OpenAI-compatible | `GET {base}/models` | شناسه و نام، به‌علاوهٔ فیلدهای صریحی که Gateway منتشر کند |
| OpenAI Chat Completions | `GET {base}/models` | مدل‌های فهرست‌شده با کلید و تطبیق اختیاری با کاتالوگ `openai`. مدل‌های تازه از پارامتر خروجی `max_completion_tokens` استفاده می‌کنند |
| OpenRouter | `GET {base}/models/user?output_modalities=all` | فهرست با ترجیحات حساب، ورودی و خروجی، سقف‌ها، پارامترها، مسیرهای سرویس و مشخصات `reasoning` در صورت ارائه |
| Ollama | `GET {root}/api/tags` | شناسهٔ مدل‌های محلی. در این آداپتور، اطلاعات معماری تک‌تک مدل‌ها از `/api/show` خوانده نمی‌شود |
| LM Studio | `GET {root}/api/v1/models` | شناسهٔ `key`، نام، نوع مدل، بینایی، اطلاعات فراخوانی ابزار و سقف Context طبق پاسخ سرور |

برای Ollama و LM Studio، `root` با برداشتن پسوند `/v1` از Base URL به دست می‌آید. برای نسخه‌ای از LM Studio که فهرست بومی v1 ندارد، نوع OpenAI-compatible را انتخاب کنید.

۳. در صورت استفاده از Models.dev، شناسهٔ دقیق Provider در Registry را وارد کنید. برای نوع OpenAI و OpenRouter پیش‌فرض به‌ترتیب `openai` و `openrouter` است. برای Gateway سفارشی، فیلد خالی یعنی Registry غیرفعال است. اتصال را ذخیره کنید و در فرم ویرایش دکمهٔ **Sync Models** را بزنید. دکمه از تنظیمات ذخیره‌شده استفاده می‌کند.

۴. گزارش تعداد مدل‌های جدید، به‌روز، بدون تغییر، غایب، ورودی تکراری و ردیف‌های نامعتبر را بخوانید. نخستین ۲۵ خطای ردیفی با شمارهٔ ردیف و کد ثبت می‌شوند. مدل تازه برای بازبینی **غیرفعال** است. در صفحهٔ مدل، جدول قابلیت مؤثر و منبع را ببینید، بودجهٔ خروجی و سیاست نمایش استدلال را بررسی کنید و مدل را فعال کنید. مدل‌های غایب و پیام‌های آن‌ها حفظ می‌شوند.

## شواهد و اولویت

برای هر فیلد، تنظیم دستی بر Metadata همان اتصال و Metadata بر Registry اولویت دارد. Registry فقط با زوج دقیق شناسهٔ Provider و شناسهٔ مدل تطبیق داده می‌شود. پنل هم دادهٔ کشف‌شده و هم مقدار مؤثر را نمایش می‌دهد. «نامعلوم» یعنی برای آن قابلیت شاهدی در دسترس نیست. تطبیق رشته‌ای نام خانواده و ارسال پیام پولی برای آزمایش جزو فرآیند شناسایی نیست.

فهرست Provider مشخص می‌کند چه شناسه‌هایی وارد سامانه شوند. Registry می‌تواند ویژگی‌های ثبت‌شده برای آن عرضهٔ مدل را تکمیل کند. برای نمونه، اگر Registry پشتیبانی ابزار را گزارش کند ولی فهرست پارامترهای OpenRouter ابزار را نپذیرد، اطلاعات endpoint اولویت دارد. فهرست‌شدن یک شناسه تضمین دسترسی لحظه‌ای به inference، موجودی اعتبار یا دسترسی به همهٔ APIهای آن مدل نیست.

برای اصلاح دستی پرچم‌ها و سقف‌های مستند، در `capability_overrides` یک شیء JSON وارد کنید، مثلاً به این شکل بنویسید.

```json
{"vision": false, "streaming": true, "context_window": 16384}
```

کلیدهای بولی شامل `text_generation`، `chat_completions`، `reasoning`، `vision`، `image_generation`، `tool_calling`، `streaming`، `structured_output` و `json_mode` هستند. `context_window` و `max_output_tokens` عدد صحیح مثبت می‌پذیرند. با حذف یک کلید، منبع بعدی دوباره مؤثر می‌شود. سقف عملیاتی گفتگو و بودجهٔ خروجی که مدیر تعیین کرده، همچنان رزرو را محدود می‌کنند. Sync بودجه یا سهمیه را خودکار افزایش نمی‌دهد. وقتی تولید متن یا مسیر Chat Completions صریحاً پشتیبانی نشود، Backend پیش از رزرو درخواست را رد می‌کند. `streaming=false` مسیر JSON را برای همان مدل انتخاب می‌کند.

## Effort و ساخت Payload

فهرست سطح‌ها و قرارداد درخواست مستقل‌اند. برای نمونه، گزینه‌های `supported_parameters[].options` برای پارامتر `reasoning_effort` هم مقادیر و هم روش ارسال را مشخص می‌کنند. افزونهٔ `supported_reasoning_efforts` در Gateway فهرست سطح‌ها را می‌دهد. برای استفاده از آن، روش ارسال هم باید از Metadata، نوع مشخص اتصال یا تنظیم دستی معلوم باشد. Registry می‌تواند `reasoning_options` را تکمیل کند. وجود یک toggle یا یک بازهٔ توکن به‌تنهایی سطح نام‌دار ایجاد نمی‌کند.

در OpenRouter بخش `reasoning.supported_efforts`، `mandatory`، `default_enabled` و `default_effort` خوانده می‌شود. مقدار صریح `null` برای فهرست در قرارداد این سرویس یعنی همهٔ Effortهای تعریف‌شدهٔ Gateway مجازند. غیبت فیلد چنین معنایی ندارد. برای مدل اجباری `none` حذف می‌شود. پیش‌فرض مشروط به فعال‌شدن استدلال، به‌تنهایی باعث فعال‌کردن آن در درخواست نمی‌شود. [قرارداد مدل OpenRouter](https://github.com/OpenRouterTeam/typescript-sdk/blob/1e9591a506fdb5675a838a5f38003667bd344c60/src/models/modelreasoning.ts)

| قرارداد | نمونهٔ انتخاب | پارامتر ارسالی |
| --- | --- | --- |
| `native_effort` | `xhigh` | `{"reasoning_effort":"xhigh"}` |
| `router_effort` | `medium` | `{"reasoning":{"effort":"medium"}}` |
| `budget_tokens` | سطح دستی `brief` با بودجهٔ ۱۰۲۴ | `{"thinking":{"type":"enabled","budget_tokens":1024}}` |

برای Override دستی Effort، گزینهٔ «استفاده از قرارداد استدلال کشف‌شده» را بردارید، قرارداد را انتخاب کنید و در `thinking_levels` آرایه‌ای مانند `["minimal","medium","xhigh"]` قرار دهید. پیش‌فرض باید عضو همان مجموعه باشد. قراردادهای جدید می‌توانند پیش‌فرض خالی داشته باشند تا در نبود انتخاب، پارامتر Effort ارسال نشود. برای `budget_tokens` نگاشت `thinking_budgets` مثل `{"brief":1024,"deep":4096}` لازم است. مقدار هر بودجه باید با قرارداد واقعی Provider سازگار و از بودجهٔ کل خروجی کمتر باشد. قراردادهای قبلی `always`، `toggle`، `effort`، `toggle_effort` و `kimi_preserved` رفتار پیشین را دارند.

API فقط سطح‌های مؤثر را به انتخابگر می‌دهد. مقدار خارج از مجموعه در Backend پیش از رزرو یا تماس شبکه رد می‌شود. شناسهٔ درخواست، سطح انتخاب‌شده و سقف عملیاتی برای هر نوبت گفتگو جدا نگهداری می‌شوند. سیاست نمایش و ذخیرهٔ متن استدلال همچنان تحت کنترل مدیر است. کشف Vision، تولید تصویر، ابزار یا JSON Mode به‌خودی‌خود رابطی برای استفاده از آن قابلیت‌ها اضافه نمی‌کند.

## Registry، شبکه و عملیات

آخرین Snapshot معتبر هر Provider در PostgreSQL ذخیره می‌شود. Sync پس از ۲۴ ساعت برای تازه‌سازی تلاش می‌کند. هنگام قطع دسترسی، Snapshot قبلی استفاده می‌شود و وضعیت `stale` در گزارش می‌آید. وقتی Snapshot موجود نیست، کشف با داده‌های خود Provider ادامه می‌یابد. در نصب آفلاین `LLM_DISCOVERY_REGISTRY_OFFLINE=true` را تنظیم کنید و یک خروجی معتبر `api.json` را وارد کنید. درخواست Registry به یک URL ثابت می‌رود و کلید Provider همراه آن ارسال نمی‌شود. [ساختار API کاتالوگ](https://github.com/sst/models.dev/blob/51bb51a3692670612b958b37d6dc24ad886ad71a/packages/sdk/src/types.ts)

```sh
docker compose exec backend python manage.py refresh_model_registry openai
docker compose cp ./api.json backend:/tmp/models-dev.json
docker compose exec backend python manage.py refresh_model_registry openai --file /tmp/models-dev.json
docker compose exec backend python manage.py sync_models 3
```

دستور آخر شناسهٔ اتصال در Admin را می‌گیرد و برای اجرای دستی یا زمان‌بندی با cron مناسب است. Sync شبکه را بیرون از تراکنش پایگاه داده انجام می‌دهد. در هر اتصال فقط یک Sync پذیرفته می‌شود. پس از قطع فرایند، اجرای جدید بعد از پنج دقیقه می‌تواند کار را از سر بگیرد. اگر اتصال در حین دریافت فهرست تغییر کرده باشد، پاسخ قبلی روی تنظیمات تازه اعمال نمی‌شود.

دریافت کاتالوگ Provider به HTTPS و مقصد عمومی محدود است. برای سرویس خصوصی، مبدأ دقیق مورد اعتماد را با scheme و port در `LLM_DISCOVERY_LOCAL_ORIGINS` وارد کنید. برای چند مبدأ از ویرگول استفاده کنید. نمونهٔ `http://127.0.0.1:11434` از داخل کانتینر Backend به همان کانتینر اشاره می‌کند. برای سرویس جدا، آدرس قابل‌دسترسی از Backend را تنظیم کنید. همهٔ IPهای حاصل از DNS بررسی می‌شوند و اتصال به IP بررسی‌شده با Host و نام TLS اصلی برقرار می‌شود. Redirect دنبال نمی‌شود. مقصدهای link-local و سرویس‌های metadata مسدود می‌شوند. مسیر Discovery پراکسی محیطی را به ارث نمی‌برد. این سیاست مربوط به دریافت کاتالوگ است. مسیر inference اتصال‌های مدیر از تنظیمات قبلی پروژه استفاده می‌کند.

برای خطای Sync، کد و HTTP Status را در گزارش اتصال بررسی کنید. `auth` به مجوز کلید، `endpoint` به نوع یا مسیر Provider و `destination` به سیاست مقصد اشاره می‌کند. فهرست باید JSON بدون فشرده‌سازی، حداکثر ۸ MiB و حداکثر ۵۰۰۰ ردیف باشد. مهلت کل هر دریافت ۲۵ ثانیه است. فهرست چندصفحه‌ای با نشانهٔ ادامه، خطای `pagination` می‌دهد و موجودی قبلی حفظ می‌شود. پاسخ خام یا هدر Authorization در گزارش ذخیره نمی‌شود.

## سازگاری و ارتقا

Migration شمارهٔ `0008_model_discovery` جداول و فیلدهای کشف، Cache و بودجه را اضافه می‌کند و طول Effort پیام‌ها را افزایش می‌دهد. مدل‌های قبلی در حالت دستی می‌مانند. مقادیر قبلی مانند `off` و `max` عیناً حفظ می‌شوند. Migration شمارهٔ `0009_unique_catalog_models` یکتایی شناسه در هر اتصال را برای رکوردهای جدید برقرار می‌کند. اگر پیش‌تر چند ردیف با یک شناسه در یک اتصال ساخته شده باشند، شناسه‌های محلی، ارجاعات و تاریخچهٔ همگی حفظ می‌شوند. Sync برای آن گروه خطای `existing_duplicates` می‌دهد تا مدیر دربارهٔ مدل‌های هم‌نام تصمیم بگیرد.

```sh
docker compose build backend cleanup web
docker compose run --rm backend python manage.py migrate
docker compose up -d backend cleanup web
docker compose exec backend python manage.py showmigrations portal
```

اگر نصب شما از tokenizer محلی استفاده می‌کند، در مرحلهٔ ساخت Backend و cleanup همان گزینهٔ `--build-arg INSTALL_LOCAL_TOKENIZERS=1` را حفظ کنید.

## بررسی پروژهٔ مرجع

Cherry Studio دریافت فهرست را به fetcherهای اختصاصی Provider می‌سپارد و کنترل‌های Reasoning را از قراردادهای Registry استخراج می‌کند. برخی مسیرهای ingest آن از الگوهای نام خانواده هم استفاده می‌کنند. در LLM Portal آداپتورها متناسب با Django و Chat Completions پیاده شده‌اند و شناسایی نیازمند دادهٔ صریح، تطبیق دقیق Registry یا تنظیم مدیر است. [فهرست مدل‌های Cherry Studio](https://github.com/CherryHQ/cherry-studio/blob/e00f061f66297fc8adcaf8ef378be67942565fac/src/main/ai/provider/listModels.ts) · [کنترل‌های Reasoning](https://github.com/CherryHQ/cherry-studio/blob/e00f061f66297fc8adcaf8ef378be67942565fac/packages/provider-registry/src/utils/reasoningControls.ts) · [قواعد تطبیق خانواده](https://github.com/CherryHQ/cherry-studio/blob/e00f061f66297fc8adcaf8ef378be67942565fac/packages/provider-registry/src/patterns/reasoning-membership.ts)
