import { VrpHistoryEntry } from './rpkilog.js';

function check_for_deeplink_in_url (event) {
    // Invoked at DOMContentLoaded.  Check the document URL and if it has get params, populate the
    // search form and invoke a query.  This allows sharing links right to a set of search results.

    let url = new URL(document.URL);
    if (url.search.length == 0) {
        return;
    }
    let params = new URLSearchParams(url.search);
    let field_list = [
        'asn',
        'observation_timestamp_start',
        'observation_timestamp_end',
        'prefix',
    ];
    for (let field of field_list) {
        if ('prefix' in params) {
            document.querySelector('#' + field).value = params[field];
        }
    }
    document.querySelector('#rpki_history_search_button').click();
}

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
    let tbody = document.querySelector("table#vrp_history_table > tbody");
    let caption = document.querySelector("#vrp_history_table > caption");
    caption.innerText = 'Posting query to rpkilog API...';
    caption.style.color = '#e4d802';
    tbody.replaceChildren();

    let copy_fields_to_query = [
        "asn",
        "observation_timestamp_start",
        "observation_timestamp_end",
        "prefix",
    ];
    let query = {};
    // Copy input form fields which require no manipulation (except URI encoding) before posting to API
    for (let field of copy_fields_to_query) {
        let input_element = document.querySelector("#" + field);
        if (input_element.value.length) {
            query[field] = input_element.value;
        }
    }

    let get_params = new URLSearchParams(query)
    fetch(rpkilog_config.api_url + '?' + get_params.toString(), {
        method: 'GET',
        cache: 'no-store',
        headers: {'Accept': 'application/json'},
        mode: 'cors',
    })
    .then(fetch_response => { return fetch_response.json(); } )
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
        caption.style.color = null;
        tbody.replaceChildren(...result_rows);
        window.history.pushState('', '', '/?' + get_params.toString());
    });
};

document.querySelector("#rpki_history_search_button").addEventListener("click", search_clicked);
addEventListener('DOMContentLoaded', check_for_deeplink_in_url);
