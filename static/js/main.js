// ============================================================
// Smart Invoice & Expense Tracker – Client-side JavaScript
// Handles: mobile menu toggle, auto-dismiss flash messages,
//          and setting today's date on date inputs.
// ============================================================

document.addEventListener("DOMContentLoaded", function () {

    // ── Mobile hamburger menu ──
    const hamburger  = document.getElementById("hamburger");
    const mobileMenu = document.getElementById("mobileMenu");

    if (hamburger && mobileMenu) {
        hamburger.addEventListener("click", function () {
            mobileMenu.classList.toggle("open");
        });

        // Close mobile menu when a link is clicked
        mobileMenu.querySelectorAll("a").forEach(function (link) {
            link.addEventListener("click", function () {
                mobileMenu.classList.remove("open");
            });
        });
    }

    // ── Auto-dismiss flash messages after 4 seconds ──
    const flashes = document.querySelectorAll(".flash");
    flashes.forEach(function (flash) {
        setTimeout(function () {
            flash.style.transition = "opacity 0.4s";
            flash.style.opacity    = "0";
            setTimeout(function () { flash.remove(); }, 400);
        }, 4000);
    });

    // ── Set today as default date for all date inputs ──
    const today = new Date().toISOString().split("T")[0]; // "YYYY-MM-DD"
    document.querySelectorAll('input[type="date"]').forEach(function (input) {
        if (!input.value) {
            input.value = today;
        }
    });

    // ── Prevent double-form submission on delete buttons ──
    document.querySelectorAll("form").forEach(function (form) {
        form.addEventListener("submit", function (e) {
            const submitBtn = form.querySelector('[type="submit"]');
            if (submitBtn && !submitBtn.disabled) {
                // Only disable after confirm dialog passes (for forms with confirm)
                setTimeout(function () {
                    submitBtn.disabled = true;
                    submitBtn.textContent = "Processing...";
                }, 10);
            }
        });
    });

});
