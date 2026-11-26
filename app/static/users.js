/* 利用者マスタの登録・編集。
 *
 * 予約と同じく /api/users（JSON）だけを使う。
 */

(() => {
  "use strict";

  const API = "/api/users";

  const modal = document.getElementById("user-modal");
  const form = document.getElementById("user-form");
  const errorBox = document.getElementById("user-form-error");
  const deleteButton = document.getElementById("btn-delete-user");
  const modalTitle = modal.querySelector(".modal-title");

  // 任意項目。フォームと送信データの両方でこの並びを使い回す。
  const OPTIONAL_FIELDS = [
    "kana",
    "condition",
    "notes",
    "training",
    "bathing_type",
    "fixed_bed_id",
    "care_manager_id",
  ];

  document.getElementById("btn-new-user").addEventListener("click", () => {
    form.reset();
    form.user_id.value = "";
    modalTitle.textContent = "利用者を登録";
    deleteButton.hidden = true;
    show();
  });

  document.addEventListener("click", (event) => {
    const button = event.target.closest(".btn-edit-user");
    if (!button) return;
    openEdit(Number(button.closest("tr").dataset.user));
  });

  async function openEdit(id) {
    let user;
    try {
      user = await request(`${API}/${id}`, "GET");
    } catch (error) {
      alert(error.message);
      return;
    }

    form.reset();
    form.user_id.value = user.id;
    form.name.value = user.name;

    const gender = form.querySelector(`input[name="gender"][value="${user.gender}"]`);
    if (gender) gender.checked = true;

    for (const field of OPTIONAL_FIELDS) {
      form[field].value = user[field] || "";
    }

    modalTitle.textContent = "利用者を編集";
    deleteButton.hidden = false;
    show();
  }

  function show() {
    errorBox.hidden = true;
    modal.hidden = false;
    form.name.focus();
  }

  function close() {
    modal.hidden = true;
  }

  document.getElementById("btn-cancel-user").addEventListener("click", close);

  modal.addEventListener("click", (event) => {
    if (event.target === modal) close();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.hidden) close();
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorBox.hidden = true;

    const payload = {
      name: form.name.value,
      gender: form.querySelector('input[name="gender"]:checked').value,
    };
    // 空欄は null で送る。サーバ側では「その項目を消す」として扱われる
    // （編集で欄を空にして保存したら、その項目が消える）。
    for (const field of OPTIONAL_FIELDS) {
      payload[field] = form[field].value || null;
    }
    if (payload.care_manager_id !== null) {
      payload.care_manager_id = Number(payload.care_manager_id);
    }

    const id = form.user_id.value;
    try {
      await request(id ? `${API}/${id}` : API, id ? "PATCH" : "POST", payload);
      location.reload();
    } catch (error) {
      errorBox.textContent = error.message;
      errorBox.hidden = false;
    }
  });

  deleteButton.addEventListener("click", async () => {
    const id = form.user_id.value;
    if (!id) return;
    if (!confirm(`「${form.name.value}」を利用者マスタから削除します。よろしいですか？`)) {
      return;
    }

    try {
      await request(`${API}/${id}`, "DELETE");
      location.reload();
    } catch (error) {
      // 予約が残っている場合はここに来る。何件残っているかが本文に入っている。
      errorBox.textContent = error.message;
      errorBox.hidden = false;
    }
  });

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
