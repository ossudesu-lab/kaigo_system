/* 問い合わせの記録・編集と、予約データへの変換。 */

(() => {
  "use strict";

  const API = "/api/inquiries";

  const modal = document.getElementById("inquiry-modal");
  const form = document.getElementById("inquiry-form");
  const errorBox = document.getElementById("inquiry-form-error");
  const deleteButton = document.getElementById("btn-delete-inquiry");
  const modalTitle = modal.querySelector(".modal-title");

  const cmSelect = document.getElementById("cm-select");
  const cmDetail = document.getElementById("cm-detail");
  const userSelect = document.getElementById("inquiry-user-select");
  const guestLabel = document.getElementById("guest-name-label");

  const convertModal = document.getElementById("convert-modal");
  const convertSummary = document.getElementById("convert-summary");
  const convertGenderSet = document.getElementById("convert-gender-set");
  const convertNote = document.getElementById("convert-tentative-note");
  const convertError = document.getElementById("convert-error");
  let convertTarget = null;

  /* ---------------------------------------------------------------- 記録・編集 */

  document.getElementById("btn-new-inquiry").addEventListener("click", () => {
    form.reset();
    form.inquiry_id.value = "";
    // 電話を受けたその場で記録することがほとんどなので、今日を初期値にする
    form.inquiry_date.value = new Date().toLocaleDateString("sv-SE");
    modalTitle.textContent = "問い合わせを記録";
    deleteButton.hidden = true;
    syncCmDetail();
    syncGuestField();
    show();
  });

  document.addEventListener("click", (event) => {
    const edit = event.target.closest(".btn-edit-inquiry");
    if (edit) {
      openEdit(Number(edit.closest("tr").dataset.inquiry));
      return;
    }

    const convert = event.target.closest(".btn-convert");
    if (convert) openConvert(Number(convert.closest("tr").dataset.inquiry));
  });

  async function openEdit(id) {
    let inquiry;
    try {
      inquiry = await request(`${API}/${id}`, "GET");
    } catch (error) {
      alert(error.message);
      return;
    }

    form.reset();
    form.inquiry_id.value = inquiry.id;
    form.inquiry_date.value = inquiry.inquiry_date;
    form.kind.value = inquiry.kind;
    form.status.value = inquiry.status;
    form.care_manager_id.value = inquiry.care_manager_id || "";
    form.user_master_id.value = inquiry.user_master_id || "";
    form.guest_name.value = inquiry.guest_name || "";
    form.desired_check_in.value = inquiry.desired_check_in || "";
    form.desired_check_out.value = inquiry.desired_check_out || "";
    form.memo.value = inquiry.memo || "";

    modalTitle.textContent = "問い合わせを編集";
    deleteButton.hidden = false;
    syncCmDetail();
    syncGuestField();
    show();
  }

  // CMを選ぶと事業所名・連絡先を出す。毎回聞き直さなくて済むように。
  function syncCmDetail() {
    const option = cmSelect.selectedOptions[0];
    const parts = [];
    if (option && option.value) {
      if (option.dataset.office) parts.push(option.dataset.office);
      if (option.dataset.phone) parts.push(`TEL ${option.dataset.phone}`);
      if (option.dataset.fax) parts.push(`FAX ${option.dataset.fax}`);
    }
    cmDetail.textContent = parts.join("　");
  }

  // マスタから選んだときは手入力欄を隠す。両方埋まっていると
  // どちらが正しいのか分からなくなるため。
  function syncGuestField() {
    guestLabel.hidden = Boolean(userSelect.value);
    if (userSelect.value) form.guest_name.value = "";
  }

  cmSelect.addEventListener("change", syncCmDetail);
  userSelect.addEventListener("change", syncGuestField);

  function show() {
    errorBox.hidden = true;
    modal.hidden = false;
  }

  function close() {
    modal.hidden = true;
  }

  document.getElementById("btn-cancel-inquiry").addEventListener("click", close);

  modal.addEventListener("click", (event) => {
    if (event.target === modal) close();
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorBox.hidden = true;

    const payload = {
      inquiry_date: form.inquiry_date.value,
      kind: form.kind.value,
      status: form.status.value,
      care_manager_id: form.care_manager_id.value
        ? Number(form.care_manager_id.value)
        : null,
      user_master_id: form.user_master_id.value
        ? Number(form.user_master_id.value)
        : null,
      guest_name: form.guest_name.value || null,
      desired_check_in: form.desired_check_in.value || null,
      desired_check_out: form.desired_check_out.value || null,
      memo: form.memo.value || null,
    };

    const id = form.inquiry_id.value;
    try {
      await request(id ? `${API}/${id}` : API, id ? "PATCH" : "POST", payload);
      location.reload();
    } catch (error) {
      errorBox.textContent = error.message;
      errorBox.hidden = false;
    }
  });

  deleteButton.addEventListener("click", async () => {
    const id = form.inquiry_id.value;
    if (!id) return;
    if (!confirm("この問い合わせを削除します。よろしいですか？")) return;

    try {
      await request(`${API}/${id}`, "DELETE");
      location.reload();
    } catch (error) {
      errorBox.textContent = error.message;
      errorBox.hidden = false;
    }
  });

  /* ---------------------------------------------------------------- 予約への変換 */

  async function openConvert(id) {
    let inquiry;
    try {
      inquiry = await request(`${API}/${id}`, "GET");
    } catch (error) {
      alert(error.message);
      return;
    }

    if (!inquiry.desired_check_in || !inquiry.desired_check_out) {
      alert("希望日程が入っていません。先に入所日と退所日を入力してください。");
      return;
    }

    convertTarget = inquiry;
    convertError.hidden = true;

    convertSummary.innerHTML =
      `<strong>${escapeHtml(inquiry.display_name)}</strong>　` +
      `${inquiry.desired_check_in} 〜 ${inquiry.desired_check_out}`;

    // 初期値は、マスタに登録済みかどうかで出し分ける。
    // 既存の方は空きがあればそのまま決まることがほとんど、
    // 新規の方はケースバイケース、という現場の実態に合わせている。
    const tentative = !inquiry.is_registered_user;
    convertModal.querySelector(
      `input[name="convert_tentative"][value="${tentative}"]`
    ).checked = true;

    convertNote.textContent = inquiry.is_registered_user
      ? "利用者マスタに登録済みの方なので、本予約を初期値にしています。"
      : "利用者マスタに未登録の方なので、仮予約を初期値にしています。";

    convertGenderSet.hidden = inquiry.is_registered_user;

    convertModal.hidden = false;
  }

  document.getElementById("btn-cancel-convert").addEventListener("click", () => {
    convertModal.hidden = true;
  });

  convertModal.addEventListener("click", (event) => {
    if (event.target === convertModal) convertModal.hidden = true;
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (!modal.hidden) close();
    if (!convertModal.hidden) convertModal.hidden = true;
  });

  document.getElementById("btn-do-convert").addEventListener("click", async () => {
    if (!convertTarget) return;
    convertError.hidden = true;

    const payload = {
      is_tentative:
        convertModal.querySelector('input[name="convert_tentative"]:checked')
          .value === "true",
    };

    if (!convertTarget.is_registered_user) {
      const gender = convertModal.querySelector(
        'input[name="convert_gender"]:checked'
      );
      if (!gender) {
        convertError.textContent = "性別を選んでください。";
        convertError.hidden = false;
        return;
      }
      payload.gender = gender.value;
    }

    try {
      const result = await request(
        `${API}/${convertTarget.id}/convert`,
        "POST",
        payload
      );
      alert(
        `予約を作成しました。\n${result.guest_name}　${result.check_in} 〜 ${result.check_out}\n` +
          `部屋は未定です。予約表の「部屋未定」リストから割り当ててください。`
      );
      location.reload();
    } catch (error) {
      convertError.textContent = error.message;
      convertError.hidden = false;
    }
  });

  /* ---------------------------------------------------------------- */

  function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value;
    return div.innerHTML;
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
