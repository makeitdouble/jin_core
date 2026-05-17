// dragdrop.js

const chatColumn = document.querySelector("#chat-drop-zone");
const fileInput = document.querySelector("#file-input");
const attachedFiles = document.querySelector("#attached-files");

let droppedFiles = [];

// -------------------------
// BLOCK GLOBAL DROP
// -------------------------

["dragenter", "dragover", "dragleave", "drop"].forEach(eventName => {

    document.addEventListener(eventName, (e) => {

        e.preventDefault();
        e.stopPropagation();

    });

});

// -------------------------
// HIGHLIGHT CHAT COLUMN
// -------------------------

["dragenter", "dragover"].forEach(eventName => {

    chatColumn.addEventListener(eventName, () => {

        chatColumn.classList.add(
            "brightness-110"
        );

    });

});

["dragleave", "drop"].forEach(eventName => {

    chatColumn.addEventListener(eventName, () => {

        chatColumn.classList.remove(
            "brightness-110"
        );

    });

});

// -------------------------
// FILE RENDER
// -------------------------

function renderFiles() {

    attachedFiles.innerHTML = "";

    droppedFiles.forEach((file, index) => {

        const item = document.createElement("div");

        item.className =
            "flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-500 border border-slate-400 text-xs text-zinc-100 shadow";

        item.innerHTML = `
            <span class="truncate max-w-[220px]">
                ${file.name}
            </span>

            <button
                class="text-zinc-200 hover:text-red-300 transition"
                data-index="${index}"
            >
                ✕
            </button>
        `;

        attachedFiles.appendChild(item);

    });

    // REMOVE BUTTONS

    attachedFiles.querySelectorAll("button").forEach(btn => {

        btn.addEventListener("click", () => {

            const index = Number(btn.dataset.index);

            droppedFiles.splice(index, 1);

            syncFileInput();
            renderFiles();

        });

    });

}

// -------------------------
// SYNC INPUT
// -------------------------

function syncFileInput() {

    const dt = new DataTransfer();

    droppedFiles.forEach(file => dt.items.add(file));

    fileInput.files = dt.files;

}

// -------------------------
// HANDLE NEW FILES
// -------------------------

function addFiles(fileList) {

    for (const file of fileList) {

        droppedFiles.push(file);

        console.log("[FILE]", {
            name: file.name,
            type: file.type,
            size: file.size
        });

    }

    syncFileInput();
    renderFiles();

}

// -------------------------
// DROP
// -------------------------

chatColumn.addEventListener("drop", (e) => {

    const files = e.dataTransfer.files;

    if (!files.length) return;

    addFiles(files);

});

// -------------------------
// MANUAL PICK
// -------------------------

fileInput.addEventListener("change", (e) => {

    addFiles(e.target.files);

});