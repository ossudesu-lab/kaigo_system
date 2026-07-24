/* 予約表の操作。
 *
 *  - 空いているマスを横にドラッグ → 離すと入力フォームが開く（仕様②）
 *  - 予約が入っているマスをクリック → その予約の編集フォームが開く
 *  - 部屋未定リストから部屋を選ぶ → その部屋に割り当てる（仕様④）
 *
 * サーバとのやりとりは /api/reservations（JSON）だけを使う。
 * 画面のHTMLを返すルートとは分けてあるので、将来フロントを別のものに
 * 差し替えても、このAPIはそのまま使える。
 */

(() => {
  "use strict";

  const API = "/api/reservations";

  const modal = document.getElementById("modal");
  const userSelect = document.getElementById("user-select");
  const form = document.getElementById("reservation-form");
  const errorBox = document.getElementById("form-error");
  const nightsNote = document.getElementById("nights-note");
  const bedNote = document.getElementById("bed-note");
  const deleteButton = document.getElementById("btn-delete");
  const modalTitle = document.querySelector(".modal-title");

  /* ------------------------------------------------------------------
   * ドラッグで範囲を選ぶ
   * ------------------------------------------------------------------ */

  // ドラッグ中の状態。started は「実際に動かし始めたか」で、
  // ただのクリックと区別するために持っている。
  let drag = null;

  // 属性セレクタの "..." の中に値を入れるための逃がし処理。
  // ここで CSS.escape は使えない。あれは識別子用で、"2026-07-11" のように
  // 数字で始まる値を "\32 026-07-11" に変えてしまい、引用符の中では
  // 何にもマッチしなくなる。
  const attr = (value) => String(value).replace(/["\\]/g, "\\$&");

  const cellsInRow = (bedId) =>
    Array.from(document.querySelectorAll(`.cell[data-bed="${attr(bedId)}"]`));

  const clearSelection = () => {
    document
      .querySelectorAll(".cell.is-selecting")
      .forEach((cell) => cell.classList.remove("is-selecting"));
  };

  const paintSelection = (bedId, fromDay, toDay) => {
    clearSelection();
    const [start, end] = fromDay <= toDay ? [fromDay, toDay] : [toDay, fromDay];
    cellsInRow(bedId).forEach((cell) => {
      const day = cell.dataset.day;
      if (day >= start && day <= end) cell.classList.add("is-selecting");
    });
  };

  document.addEventListener("mousedown", (event) => {
    const cell = event.target.closest(".cell");
    if (!cell) return;

    // 予約が入っているマスは、ドラッグではなくクリック（編集）として扱う。
    // 重複しているマスは段の途中が空いていることもあるが、そこも新規の
    // ドラッグ元にはしない（重なりを増やす操作を誘発しないため）。
    if (cell.querySelector(".bar")) return;

    event.preventDefault();
    drag = {
      bedId: cell.dataset.bed,
      startDay: cell.dataset.day,
      currentDay: cell.dataset.day,
    };
    paintSelection(drag.bedId, drag.startDay, drag.currentDay);
  });

  document.addEventListener("mouseover", (event) => {
    if (!drag) return;
    const cell = event.target.closest(".cell");
    if (!cell) return;

    // 同じ部屋の行の中だけで範囲を広げる。
    // 縦にはみ出しても、行をまたいだ予約にはしない。
    if (cell.dataset.bed !== drag.bedId) return;

    drag.currentDay = cell.dataset.day;
    paintSelection(drag.bedId, drag.startDay, drag.currentDay);
  });

  document.addEventListener("mouseup", () => {
    if (!drag) return;

    const { bedId, startDay, currentDay } = drag;
    drag = null;
    clearSelection();

    const [checkIn, checkOut] =
      startDay <= currentDay ? [startDay, currentDay] : [currentDay, startDay];

    openCreateModal({ bedId, checkIn, checkOut });
  });

  /* ------------------------------------------------------------------
   * 予約が入っているマスをクリック → 編集
   * ------------------------------------------------------------------ */

  document.addEventListener("click", (event) => {
    const jump = event.target.closest(".conflict-jump");
    if (jump) {
      jumpToCell(jump.dataset.bed, jump.dataset.day);
      return;
    }

    // 段（bar）ごとに予約が違うので、押した段の予約を開く。
    const bar = event.target.closest(".bar");
    if (bar && bar.dataset.reservation) {
      openEditModal(Number(bar.dataset.reservation));
      return;
    }

    const editButton = event.target.closest(".btn-edit");
    if (editButton) {
      const item = editButton.closest(".unassigned-item");
      openEditModal(Number(item.dataset.reservation));
      return;
    }

    if (event.target.closest(".btn-new-unassigned")) {
      openCreateModal({ bedId: null, checkIn: "", checkOut: "" });
    }
  });

  /* ------------------------------------------------------------------
   * 重複警告から該当のマスへ飛ぶ
   * ------------------------------------------------------------------ */

  // 光らせておく時間。CSS の cell-flash（0.5秒 × 4回）と合わせてある。
  const FLASH_MS = 2000;
  let flashTimer = null;

  function jumpToCell(bedId, day) {
    if (!bedId || !day) return;

    const cell = document.querySelector(
      `.cell[data-bed="${attr(bedId)}"][data-day="${attr(day)}"]`
    );
    if (!cell) return;

    // 部屋の列も日付の行も固定表示なので、両方向とも真ん中に寄せる。
    cell.scrollIntoView({ behavior: "smooth", block: "center", inline: "center" });

    // 続けて別の警告を押したとき、前の光が残らないようにしてから付け直す。
    clearTimeout(flashTimer);
    document
      .querySelectorAll(".cell.is-flash")
      .forEach((c) => c.classList.remove("is-flash"));

    // クラスを外してすぐ付け直すだけではアニメーションが再生されないので、
    // 一度レイアウトを確定させて仕切り直す。
    void cell.offsetWidth;

    cell.classList.add("is-flash");
    flashTimer = setTimeout(() => cell.classList.remove("is-flash"), FLASH_MS);
  }

  /* ------------------------------------------------------------------
   * 部屋未定リストから部屋を割り当てる
   * ------------------------------------------------------------------ */

  document.addEventListener("change", async (event) => {
    const select = event.target.closest(".assign-select");
    if (!select || !select.value) return;

    const item = select.closest(".unassigned-item");
    const id = Number(item.dataset.reservation);

    try {
      await request(`${API}/${id}/assign`, "POST", { bed_id: select.value });
      location.reload();
    } catch (error) {
      alert(error.message);
      select.value = "";
    }
  });

  /* ------------------------------------------------------------------
   * 部屋未定パネルの幅をドラッグで調整する
   * ------------------------------------------------------------------ */

  (function initPanelResizer() {
    const panel = document.querySelector(".unassigned");
    const resizer = document.querySelector(".col-resizer");
    if (!panel || !resizer) return;

    const MIN = 160;
    const MAX = 640;
    const KEY = "unassigned-panel-width";

    // 前回調整した幅を覚えておき、開き直しても保つ。
    const saved = Number(localStorage.getItem(KEY));
    if (saved >= MIN && saved <= MAX) panel.style.width = saved + "px";

    let startX = 0;
    let startWidth = 0;

    const onMove = (event) => {
      // 右側のパネルなので、左へドラッグするほど幅が広がる。
      const width = Math.max(MIN, Math.min(MAX, startWidth + (startX - event.clientX)));
      panel.style.width = width + "px";
    };

    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      document.body.classList.remove("is-col-resizing");
      localStorage.setItem(KEY, parseInt(panel.style.width, 10));
    };

    resizer.addEventListener("mousedown", (event) => {
      event.preventDefault();
      startX = event.clientX;
      startWidth = panel.getBoundingClientRect().width;
      document.body.classList.add("is-col-resizing");
      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });

    // ダブルクリックで既定の幅（CSS任せ）に戻す。
    resizer.addEventListener("dblclick", () => {
      panel.style.width = "";
      localStorage.removeItem(KEY);
    });
  })();

  /* ------------------------------------------------------------------
   * 部屋未定パネルをたたむ／開く
   *
   * 表そのものを広く一望したいとき、右の部屋未定パネルを右へたたんで
   * 細い縦タブだけにする。たたむと col-resizer も隠れ、グリッドが横幅を
   * 目いっぱい使う。状態は localStorage に覚えておき、開き直しても保つ。
   * ------------------------------------------------------------------ */

  (function initPanelCollapse() {
    const layout = document.querySelector(".layout");
    if (!layout) return;

    const KEY = "unassigned-panel-collapsed";

    const setCollapsed = (collapsed) => {
      layout.classList.toggle("is-panel-collapsed", collapsed);
      localStorage.setItem(KEY, collapsed ? "1" : "0");
      // 幅が変わってグリッドの可視領域が変わるので、高さ合わせをやり直す。
      window.dispatchEvent(new Event("resize"));
    };

    // 前回たたんでいたら、その状態で開く。
    if (localStorage.getItem(KEY) === "1") {
      layout.classList.add("is-panel-collapsed");
    }

    document.addEventListener("click", (event) => {
      if (event.target.closest(".panel-collapse")) setCollapsed(true);
      else if (event.target.closest(".unassigned-tab")) setCollapsed(false);
    });
  })();

  /* ------------------------------------------------------------------
   * グリッドと部屋未定パネルの高さを、画面の残りにぴったり合わせる
   *
   * 見出し部（重複警告など）の高さは件数で変わるので、CSSの固定値
   * （max-height: calc(100vh - 130px)）だと合わず、グリッドが画面下に
   * はみ出して最終行が内側スクロールで届かなくなる。そうなるとページ
   * 全体をスクロールするしかなく、その瞬間に見出しの固定（sticky）が
   * 外れてしまう。ここで各スクロール領域の「上端の位置」を実測し、
   * 高さを画面の残りぶんに合わせることで、内側スクロールだけで最終行
   * まで届き、ページ自体はスクロールしない（＝stickyが外れない）状態にする。
   * ------------------------------------------------------------------ */

  (function initFitHeights() {
    const wrap = document.querySelector(".grid-wrap");
    const panel = document.querySelector(".unassigned");
    const resizer = document.querySelector(".col-resizer");
    if (!wrap) return;

    const GAP = 6; // 画面下にわずかな余白を残す（縦を稼ぐため控えめに）
    const MIN = 160; // 見出しが極端に高い時でも、最低これだけは高さを残す

    // 現在のスクロール位置に左右されないよう、ドキュメント先頭からの
    // 距離で上端を測り、画面の高さから引いて可視領域ぶんの高さを出す。
    const available = (el) => {
      const docTop = el.getBoundingClientRect().top + window.scrollY;
      return Math.max(MIN, window.innerHeight - docTop - GAP);
    };

    const fit = () => {
      wrap.style.maxHeight = available(wrap) + "px";
      if (panel) panel.style.maxHeight = available(panel) + "px";
      if (resizer) resizer.style.minHeight = available(resizer) + "px";
    };

    fit();
    // 初回はフォント確定などでわずかにずれることがあるので、次フレームで再計測。
    requestAnimationFrame(fit);
    window.addEventListener("resize", fit);
  })();

  /* ------------------------------------------------------------------
   * フォーム
   * ------------------------------------------------------------------ */

  function openCreateModal({ bedId, checkIn, checkOut }) {
    form.reset();
    form.reservation_id.value = "";
    form.bed_id.value = bedId || "";
    form.check_in.value = checkIn;
    form.check_out.value = checkOut;

    modalTitle.textContent = "予約を追加";
    deleteButton.hidden = true;
    bedNote.textContent = bedId
      ? `部屋：${bedId}`
      : "部屋は未定です。保存すると「部屋未定」リストに入ります。";

    showModal();
    userSelect.focus();
  }

  async function openEditModal(id) {
    let reservation;
    try {
      reservation = await request(`${API}/${id}`, "GET");
    } catch (error) {
      alert(error.message);
      return;
    }

    form.reset();
    form.reservation_id.value = reservation.id;
    form.bed_id.value = reservation.bed_id || "";
    form.user_master_id.value = reservation.user_master_id;
    form.check_in.value = reservation.check_in;
    form.check_out.value = reservation.check_out;
    form.is_tentative.checked = reservation.is_tentative;

    modalTitle.textContent = "予約を編集";
    deleteButton.hidden = false;
    bedNote.textContent = reservation.bed_id
      ? `部屋：${reservation.bed_id}`
      : "部屋は未定です。";

    showModal();
  }

  // 選んでいる利用者の名前。確認メッセージに使う。
  function selectedUserName() {
    const option = userSelect.selectedOptions[0];
    return option ? option.textContent.replace(/（.*）$/, "") : "この";
  }

  function showModal() {
    errorBox.hidden = true;
    updateNights();
    modal.hidden = false;
  }

  function closeModal() {
    modal.hidden = true;
  }

  // 泊数を出して、入力ミスに気づけるようにする。
  // 退所日当日は泊まらないので、日数の差がそのまま泊数になる。
  function updateNights() {
    const checkIn = form.check_in.value;
    const checkOut = form.check_out.value;

    if (!checkIn || !checkOut) {
      nightsNote.textContent = "";
      return;
    }

    const nights = Math.round(
      (new Date(checkOut) - new Date(checkIn)) / 86400000
    );

    if (nights < 0) {
      nightsNote.textContent = "⚠ 退所日が入所日より前になっています";
      return;
    }
    nightsNote.textContent =
      nights === 0 ? "日帰り（0泊）" : `${nights}泊${nights + 1}日`;
  }

  form.check_in.addEventListener("change", updateNights);
  form.check_out.addEventListener("change", updateNights);

  // 固定部屋のある利用者を選んだとき、部屋が未定ならその部屋を初期値にする。
  // あくまで初期値で、実際にどこに入るかは予約ごとに決められる。
  userSelect.addEventListener("change", () => {
    if (form.reservation_id.value) return; // 編集中は部屋を勝手に動かさない
    if (form.bed_id.value) return; // ドラッグで部屋が決まっている場合はそのまま

    const fixedBed = userSelect.selectedOptions[0]?.dataset.fixedBed;
    if (!fixedBed) return;

    form.bed_id.value = fixedBed;
    bedNote.textContent = `部屋：${fixedBed}（この方の固定部屋です）`;
  });

  document.getElementById("btn-cancel").addEventListener("click", closeModal);

  modal.addEventListener("click", (event) => {
    if (event.target === modal) closeModal();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.hidden) closeModal();
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorBox.hidden = true;

    const id = form.reservation_id.value;
    const payload = {
      user_master_id: Number(form.user_master_id.value),
      check_in: form.check_in.value,
      check_out: form.check_out.value,
      is_tentative: form.is_tentative.checked,
    };

    try {
      if (id) {
        // 編集。部屋の移動は割り当ての操作なので、ここでは触らない。
        await request(`${API}/${id}`, "PATCH", payload);
      } else {
        payload.bed_id = form.bed_id.value || null;
        await request(API, "POST", payload);
      }
      location.reload();
    } catch (error) {
      errorBox.textContent = error.message;
      errorBox.hidden = false;
    }
  });

  deleteButton.addEventListener("click", async () => {
    const id = form.reservation_id.value;
    if (!id) return;
    if (!confirm(`「${selectedUserName()}」の予約を削除します。よろしいですか？`)) {
      return;
    }

    try {
      await request(`${API}/${id}`, "DELETE");
      location.reload();
    } catch (error) {
      errorBox.textContent = error.message;
      errorBox.hidden = false;
    }
  });

  /* ------------------------------------------------------------------ */

  async function request(url, method, body) {
    const options = { method, headers: {} };
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }

    const response = await fetch(url, options);

    if (!response.ok) {
      // FastAPI はエラーを { "detail": "..." } で返す
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
