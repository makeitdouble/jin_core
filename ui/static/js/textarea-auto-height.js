const textarea = document.getElementById("user-input");

textarea.addEventListener("input", function () {

    this.style.height = "auto";
    this.style.height = this.scrollHeight + "px";

});
