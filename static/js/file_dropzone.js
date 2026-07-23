(() => {
    const formatFileSize = (size) => {
        if (size < 1024) {
            return `${size} B`;
        }
        if (size < 1024 * 1024) {
            return `${(size / 1024).toFixed(1)} KB`;
        }
        return `${(size / (1024 * 1024)).toFixed(1)} MB`;
    };

    const setInputFiles = (input, files) => {
        const transfer = new DataTransfer();
        files.forEach((file) => transfer.items.add(file));
        input.files = transfer.files;
    };

    const renderFileList = (input, list, selectedFiles) => {
        list.innerHTML = "";
        selectedFiles.forEach((file, index) => {
            const item = document.createElement("li");
            item.className = "small d-flex flex-wrap align-items-center gap-2";

            const label = document.createElement("span");
            label.textContent = `${file.name} (${formatFileSize(file.size)})`;

            const removeButton = document.createElement("button");
            removeButton.type = "button";
            removeButton.className = "btn btn-sm btn-outline-danger py-0";
            removeButton.textContent = "Удалить";
            removeButton.addEventListener("click", () => {
                selectedFiles.splice(index, 1);
                setInputFiles(input, selectedFiles);
                renderFileList(input, list, selectedFiles);
            });

            item.append(label, removeButton);
            list.appendChild(item);
        });
    };

    const mergeFiles = (input, selectedFiles, droppedFiles) => {
        if (!input.multiple) {
            return Array.from(droppedFiles || []).slice(0, 1);
        }

        return selectedFiles.concat(Array.from(droppedFiles || []));
    };

    document.querySelectorAll("[data-file-dropzone]").forEach((zone) => {
        const input = zone.querySelector('input[type="file"]');
        const list = zone.querySelector("[data-file-list]");
        if (!input || !list) {
            return;
        }

        let selectedFiles = Array.from(input.files || []);

        input.addEventListener("change", () => {
            selectedFiles = Array.from(input.files || []);
            renderFileList(input, list, selectedFiles);
        });

        ["dragenter", "dragover"].forEach((eventName) => {
            zone.addEventListener(eventName, (event) => {
                event.preventDefault();
                zone.classList.add("is-dragover");
            });
        });

        ["dragleave", "drop"].forEach((eventName) => {
            zone.addEventListener(eventName, () => {
                zone.classList.remove("is-dragover");
            });
        });

        zone.addEventListener("drop", (event) => {
            event.preventDefault();
            const files = event.dataTransfer?.files;
            if (!files || files.length === 0) {
                return;
            }

            selectedFiles = mergeFiles(input, selectedFiles, files);
            setInputFiles(input, selectedFiles);
            renderFileList(input, list, selectedFiles);
        });
    });
})();
