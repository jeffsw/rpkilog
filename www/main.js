import { VrpHistoryEntry } from './rpkilog.js';

function create_vrp_history_row (history_entry) {
    let row = document.querySelector("#vrp_history_row").cloneNode(true);
    //FIXME: This is not how you select children.  Need to look it up.
    row.querySelector("[data-field-name='prefix']").innerText(history_entry.prefix);
    row.querySelector("[data-field-name='maxLength']").innerText(history_entry.maxLength);
    return row;
};

function my_onload(event) {
    let sample_history_entry = {
        "asn": 9583,
        "maxLength": 24,
        "new_expires": "2023-01-05T10:51:39Z",
        "new_roa": {
            "asn": 9583,
            "expires": 1672915899,
            "maxLength": 24,
            "prefix": "1.6.4.0/22",
            "ta": "apnic"
        },
        "observation_timestamp": "2022-12-29T11:05:36Z",
        "old_expires": "2023-01-05T06:31:42Z",
        "old_roa": {
            "asn": 9583,
            "expires": 1672900302,
            "maxLength": 24,
            "prefix": "1.6.4.0/22",
            "ta": "apnic"
        },
        "prefix": "1.6.4.0/22",
        "ta": "apnic",
        "verb": "REPLACE",
    };
    let table = document.querySelector("table#vrp_history_table");
    let tbody = table.querySelector("tbody");
    tbody.appendChild(create_vrp_history_row(sample_history_entry));
};

document.addEventListener("DOMContentLoaded", my_onload);
