(function () {
    function setupKeyboardToggle(root) {
        root.querySelectorAll(".order-summary-row").forEach((row) => {
            if (row.dataset.keyboardToggleReady === "1") {
                return;
            }
            row.dataset.keyboardToggleReady = "1";
            row.addEventListener("keydown", (event) => {
                if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    row.click();
                }
            });
        });
    }

    function takeNextUrl(target) {
        const marker = target.querySelector("[data-next-page-url]");
        if (!marker) {
            return "";
        }
        const url = marker.dataset.nextPageUrl || "";
        marker.remove();
        return url;
    }

    function setupInfiniteScroll(container) {
        const target = document.querySelector(container.dataset.infiniteTarget);
        const sentinel = container.querySelector("[data-infinite-sentinel]");
        if (!target || !sentinel) {
            return;
        }

        let nextUrl = takeNextUrl(target);
        let isLoading = false;

        setupKeyboardToggle(target);

        if (!nextUrl) {
            sentinel.textContent = "Все записи загружены";
            return;
        }

        const observer = new IntersectionObserver(
            (entries) => {
                if (!entries.some((entry) => entry.isIntersecting) || isLoading || !nextUrl) {
                    return;
                }
                isLoading = true;
                sentinel.textContent = "Загрузка...";
                fetch(nextUrl, {headers: {"X-Requested-With": "XMLHttpRequest"}})
                    .then((response) => {
                        if (!response.ok) {
                            throw new Error("Load failed");
                        }
                        return response.text();
                    })
                    .then((html) => {
                        target.insertAdjacentHTML("beforeend", html);
                        setupKeyboardToggle(target);
                        nextUrl = takeNextUrl(target);
                        sentinel.textContent = nextUrl ? "Прокрутите ниже для загрузки" : "Все записи загружены";
                        if (!nextUrl) {
                            observer.disconnect();
                        }
                    })
                    .catch(() => {
                        sentinel.textContent = "Не удалось загрузить записи";
                    })
                    .finally(() => {
                        isLoading = false;
                    });
            },
            {rootMargin: "600px 0px"}
        );

        observer.observe(sentinel);
    }

    document.addEventListener("DOMContentLoaded", () => {
        document.querySelectorAll("[data-infinite-scroll]").forEach(setupInfiniteScroll);
    });
})();
