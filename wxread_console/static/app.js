document.querySelectorAll("[data-confirm]").forEach((element) => {
  element.addEventListener("click", (event) => {
    if (!window.confirm(element.dataset.confirm)) {
      event.preventDefault();
    }
  });
});

if (document.querySelector("[data-running='true']")) {
  window.setTimeout(() => window.location.reload(), 3000);
}
