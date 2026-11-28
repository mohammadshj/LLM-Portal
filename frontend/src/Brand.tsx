import brand from "../public/brand/settings.json";

export function Brand({
  variant = "sidebar",
}: {
  variant?: "sidebar" | "icon" | "login";
}) {
  const full = variant === "login";
  return (
    <div className={"brand brand-" + variant}>
      <span className="brand-image">
        <img
          className="light-logo"
          src={"/brand/" + (full ? brand.signature : brand.symbol)}
          alt={variant === "icon" ? brand.product : ""}
        />
        <img
          className="dark-logo"
          src={"/brand/" + (full ? brand.signatureDark : brand.symbolDark)}
          alt={variant === "icon" ? brand.product : ""}
        />
      </span>
      {variant !== "icon" && (
        <div>
          <strong dir="ltr">{brand.product}</strong>
          <small>{brand.subtitle}</small>
        </div>
      )}
    </div>
  );
}
