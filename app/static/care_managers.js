/* CMマスタの登録・編集。 */

(() => {
  "use strict";

  const API = "/api/care-managers";
  const FIELDS = ["office", "phone", "fax", "email", "notes"];

  const modal = document.getElementById("cm-modal");
  const form = document.getElementById("cm-form");
  const errorBox = document.getElementById("cm-form-error");
  const deleteButton = document.getElementById("btn-delete-cm");
  const modalTitle = modal.querySelector(".modal-title");

  document.getElementById("btn-new-cm").addEventListener("click", () => {
    form.reset();
    form.cm_id.value = "";
    modalTitle.textContent = "CMを登録";
    deleteButton.hidden = true;
    show();
  });

  document.addEventListener("click", (event) => {
    const button = event.target.closest(".btn-edit-cm");
    if (button) openEdit(Number(button.closest("tr").dataset.cm));
  });

  async function openEdit(id) {
    let cm;
    try {
      cm = await request(`${API}/${id}`, "GET");
    } catch (error) {
      alert(error.message);
      return;
    }

    form.reset();
    form.cm_id.value = cm.id;
    form.name.value = cm.name;
    for (const field of FIELDS) form[field].value = cm[field] || "";

    modalTitle.textContent = "CMを編集";
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

  document.getElementById("btn-cancel-cm").addEventListener("click", close);

  modal.addEventListener("click", (event) => {
    if (event.target === modal) close();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.hidden) close();
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorBox.hidden = true;

    const payload = { name: form.name.value };
    for (const field of FIELDS) payload[field] = form[field].value || null;

    const id = form.cm_id.value;
    try {
      await request(id ? `${API}/${id}` : API, id ? "PATCH" : "POST", payload);
      location.reload();
    } catch (error) {
      errorBox.textContent = error.message;
      errorBox.hidden = false;
    }
  });

  deleteButton.addEventListener("click", async () => {
    const id = form.cm_id.value;
    if (!id) return;
    if (!confirm(`「${form.name.value}」をCMマスタから削除します。よろしいですか？`)) {
      return;
    }

    try {
      await request(`${API}/${id}`, "DELETE");
      location.reload();
    } catch (error) {
      // 利用者や問い合わせから参照されている場合はここに来る
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
