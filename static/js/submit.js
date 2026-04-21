// Submit page: toggles the custom command field and prefills CWD from the
// selected preset. The form itself POSTs normally (keeps no-JS fallback).

const presetSelect = document.getElementById('preset');
const customGroup = document.getElementById('custom-command-group');
const customInput = document.getElementById('custom_command');
const cwdInput = document.getElementById('cwd');
const defaultCwd = document.body.dataset.defaultCwd || '';

function toggleCustomCommand() {
    const isCustom = presetSelect.value === 'custom';
    customGroup.style.display = isCustom ? 'block' : 'none';
    customInput.required = isCustom;

    if (!isCustom) {
        const option = presetSelect.options[presetSelect.selectedIndex];
        const presetCwd = option ? option.getAttribute('data-cwd') : '';
        cwdInput.value = presetCwd || defaultCwd;
    }
}

presetSelect.addEventListener('change', toggleCustomCommand);
toggleCustomCommand();
