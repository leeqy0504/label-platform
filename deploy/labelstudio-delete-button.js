(function () {
  "use strict";

  const buttonAttribute = "data-label-platform-delete-button";
  const toolbarAnchorXPath =
    "/html/body/div[1]/div[1]/div[2]/div/div/div/div[1]/div/div[2]/div/div/div[2]/div/div[1]/div[2]/div[2]/div/div/div/button/span";
  let syncScheduled = false;

  function findDeleteChoice() {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node = walker.nextNode();
    while (node) {
      const parent = node.parentElement;
      if (
        node.textContent.trim() === "删除图片" &&
        parent &&
        !parent.closest(`[${buttonAttribute}]`)
      ) {
        return (
          parent.closest('label, button, [role="checkbox"], [role="radio"]') || parent
        );
      }
      node = walker.nextNode();
    }
    return null;
  }

  function isChoiceSelected(choice) {
    const input = choice.matches("input") ? choice : choice.querySelector("input");
    if (input instanceof HTMLInputElement) {
      return input.checked;
    }
    return (
      choice.getAttribute("aria-checked") === "true" ||
      choice.getAttribute("aria-pressed") === "true" ||
      choice.getAttribute("data-checked") === "true"
    );
  }

  function findToolbarAnchor() {
    const result = document.evaluate(
      toolbarAnchorXPath,
      document,
      null,
      XPathResult.FIRST_ORDERED_NODE_TYPE,
      null,
    );
    const exactAnchor =
      result.singleNodeValue instanceof Element
        ? result.singleNodeValue.closest("button")
        : null;
    return (
      exactAnchor ||
      document.querySelector(
        'button[aria-label="Submit current annotation"], button[aria-label="Update current annotation"]',
      )
    );
  }

  function updateButton(button, selected) {
    const label = selected ? "恢复图片" : "删除图片";
    const pressed = String(selected);
    if (button.textContent !== label) button.textContent = label;
    if (button.getAttribute("aria-pressed") !== pressed) {
      button.setAttribute("aria-pressed", pressed);
    }
    button.title = selected ? "取消删除标记" : "从审核导出的新版本中删除这张图片";
    button.style.background = selected ? "#dc2626" : "#ffffff";
    button.style.color = selected ? "#ffffff" : "#b91c1c";
  }

  function createButton() {
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute(buttonAttribute, "true");
    button.style.display = "inline-flex";
    button.style.alignItems = "center";
    button.style.justifyContent = "center";
    button.style.height = "32px";
    button.style.padding = "0 12px";
    button.style.marginRight = "8px";
    button.style.border = "1px solid #dc2626";
    button.style.borderRadius = "4px";
    button.style.fontSize = "13px";
    button.style.fontWeight = "600";
    button.style.letterSpacing = "0";
    button.style.whiteSpace = "nowrap";
    button.style.cursor = "pointer";
    button.addEventListener("click", function () {
      findDeleteChoice()?.click();
      window.setTimeout(scheduleSync, 0);
    });
    return button;
  }

  function syncButton() {
    syncScheduled = false;
    const choice = findDeleteChoice();
    const anchor = findToolbarAnchor();
    const existing = document.querySelector(`[${buttonAttribute}]`);
    if (!choice || !anchor) {
      existing?.remove();
      return;
    }

    const button = existing || createButton();
    if (!existing || button.nextElementSibling !== anchor) {
      anchor.insertAdjacentElement("beforebegin", button);
    }
    updateButton(button, isChoiceSelected(choice));
  }

  function scheduleSync() {
    if (syncScheduled) return;
    syncScheduled = true;
    window.requestAnimationFrame(syncButton);
  }

  new MutationObserver(scheduleSync).observe(document.documentElement, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["aria-checked", "aria-pressed", "checked", "data-checked"],
  });
  document.addEventListener("change", scheduleSync, true);
  scheduleSync();
})();
