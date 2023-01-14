import { VrpHistoryEntry } from './rpkilog.js';

function create_vrp_history_row (history_entry) {
    // Munge some data for presentation
    let history_clone = JSON.parse(JSON.stringify(history_entry));
    for (let k of ['old_roa', 'new_roa']) {
        if (k in history_clone) {
            let date_obj = new Date(history_clone[k].expires * 1000);
            let date_str = date_obj.toISOString();
            let date_str_without_milliseconds = date_str.replace(/\.\d+/, '');
            history_clone[k].expires = date_str_without_milliseconds;
        }
    }

    let row = document.querySelector("#vrp_history_row").content.querySelector("tr").cloneNode(true);
    row.id = null;

    const text_fields_with_old_and_new = [
        'prefix',
        'maxLength',
        'asn',
        'ta',
        'expires',
    ]
    for (let fn of text_fields_with_old_and_new) {
        let cell = row.querySelector(`[data-field-name='${fn}']`);
        let deleted, inserted;
        switch (history_clone.verb) {
            case 'UNCHANGED':
                cell.innerText = history_clone.new_roa[fn];
                break;
            case 'NEW':
                inserted = document.createElement('INS');
                inserted.innerText = history_clone.new_roa[fn];
                cell.appendChild(inserted);
                break;
            case 'DELETE':
                deleted = document.createElement('DEL');
                deleted.innerText = history_clone.old_roa[fn];
                cell.appendChild(deleted);
                break;
            case 'REPLACE':
                if (history_clone.old_roa[fn] === history_clone.new_roa[fn]) {
                    // Identical values, so the output needs to make that clear
                    cell.innerText = history_clone.new_roa[fn];
                } else {
                    // Changed values will get a strikethrough effect so it's obvious what is different
                    deleted = document.createElement('DEL');
                    deleted.innerText = history_clone.old_roa[fn];
                    cell.appendChild(deleted);
                    cell.appendChild(document.createElement('BR'))
                    inserted = document.createElement('INS');
                    inserted.innerText = history_clone.new_roa[fn];
                    cell.appendChild(inserted);    
                }
                break;
            default:
                console.error(`Unrecognized vrp_diff verb ${history_clone.verb}`, history_clone);
        }
    }
    let verb_cell = row.querySelector("[data-field-name='verb']");
    verb_cell.innerText = history_clone.verb;
    let obstime_cell = row.querySelector("[data-field-name='observation_timestamp']");
    obstime_cell.innerText = history_clone.observation_timestamp;

    return row;
};

var rpki_result = {};

function search_clicked (event) {
    let prefix_input = document.querySelector("#prefix");
    let tbody = document.querySelector("table#vrp_history_table > tbody");
    let caption = document.querySelector("#vrp_history_table > caption");
    caption.innerText = 'Posting query to rpkilog API';
    tbody.replaceChildren();

    fetch(rpkilog_config.api_url, {
        method: 'POST',
        headers: {'Accept': 'application/json'},
        body: JSON.stringify({prefix: prefix_input.value}),
    })
    .then(fetch_response => fetch_response.json())
    .then(json_body => {
        rpki_result = json_body;
        let result_rows = new Array();
        for (let history_entry of json_body.hits.hits) {
            result_rows.push(create_vrp_history_row(history_entry._source));
        }
        let caption = document.querySelector("#vrp_history_table > caption");
        caption.innerText = `took: ${json_body.took}ms `
        caption.innerText += ` shards: ${json_body._shards.total}`;
        if (json_body.hits.total.value >= 10000) {
            caption.innerText += ' hits: >= 10000';
        } else {
            caption.innerText += ` hits: ${json_body.hits.total.value}`;
        }
        tbody.replaceChildren(...result_rows);
    });
};

document.querySelector("#rpki_history_search_button").addEventListener("click", search_clicked);
