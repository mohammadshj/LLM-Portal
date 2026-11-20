import type { Usage } from "./types";
import { number } from "./ui";
export function UsageReport({ report }: { report: Usage }) {
  return (
    <section className="report">
      <h2>مصرف کاربران</h2>
      <table>
        <thead>
          <tr>
            <th>کاربر</th>
            <th>مصرف</th>
            <th>سهمیه</th>
          </tr>
        </thead>
        <tbody>
          {report.accounts.map((a) => (
            <tr key={a.user__username}>
              <td>{a.user__username}</td>
              <td>{number(a.tokens_used)}</td>
              <td>{number(a.token_limit)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h2>مصرف مدل‌ها</h2>
      <table>
        <thead>
          <tr>
            <th>مدل</th>
            <th>ورودی</th>
            <th>خروجی</th>
            <th>جمع توکن‌ها</th>
          </tr>
        </thead>
        <tbody>
          {report.models.map((m) => (
            <tr key={m.model_id}>
              <td>{m.model__name}</td>
              <td>{number(m.input_tokens)}</td>
              <td>{number(m.output_tokens)}</td>
              <td>
                {number(m.input_tokens + m.output_tokens + m.unsplit_tokens)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
