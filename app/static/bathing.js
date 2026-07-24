/* 入浴日の調整（1週間分の画面）。
 *
 * 自動で出した候補を現場が動かせるようにする（daily_reports_spec.md 3）。
 * 一度でも動かした予約は自動計算から外れ、以降は手動の内容が使われる。
 */

(() => {
  "use strict";

  const API = "/api/reports/bathing-days";

  document.addEventListener("click", async (event) => {
    const toggle = event.target.closest(".bath-toggle");
    if (toggle) {
      await toggleDay(toggle);
      return;
    }

    const reset = event.target.closest(".btn-reset");
    if (reset) await resetRow(reset.closest("tr"));
  });

  async function toggleDay(button) {
    const row = button.closest("tr");
    const id = Number(row.dataset.reservation);

    // 画面に出ているのは1週間ぶんだけなので、その外の入浴日を消さないよう
    // 現在の全期間の入浴日をサーバから取り直してから足し引きする。
    let current;
    try {
      current = await request(`${API}/${id}`, "GET");
    } catch (error) {
      alert(error.message);
      return;
    }

    const day = button.dataset.day;
    const days = new Set(current.days);
    days.has(day) ? days.delete(day) : days.add(day);

    try {
      await request(`${API}/${id}`, "PUT", { days: [...days].sort() });
      location.reload();
    } catch (error) {
      alert(error.message);
    }
  }

  async function resetRow(row) {
    const id = Number(row.dataset.reservation);
    if (!confirm("手動で調整した入浴日を捨てて、自動の候補に戻します。よろしいですか？")) {
      return;
    }

    try {
      await request(`${API}/${id}`, "DELETE");
      location.reload();
    } catch (error) {
      alert(error.message);
    }
  }

  async function request(url, method, body) {
    const options = { method, headers: {} };
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }

    const response = await fetch(url, options);

    if (!response.ok) {
      let message = `通信に失敗しました（${response.status}）`;
      try {
        const data = await response.json();
        if (typeof data.detail === "string") message = data.detail;
      } catch {
        /* JSONで返ってこない場合はそのままのメッセージを使う */
      }
      throw new Error(message);
    }

    return response.status === 204 ? null : response.json();
  }
})();
