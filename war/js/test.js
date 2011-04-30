function checkSignedRequest() {
    $.getJSON('/ajax/decode-signed-request/' + $("#signed-request").val(), null, function(result) {
        if (result) {
            $("#facebook-token").val(result.oauth_token);
            $("#output").val("Valid signed_request :-)\n\n" + $.toJSON(result));
            $("#signed-request").addClass('valid').removeClass('wrong');
        }
        else {
            $("#signed-request").addClass('wrong').removeClass('valid');
            $("#output").val("Dodgy signed_request >:o");
        }
    });
}

$(document).ready(function() {
    $("#signed-request").keydown(function(event) {
        checkSignedRequest();
    });

    $("#scrape-birthdays").click(function(event) {
        event.preventDefault();
        $.getJSON('/ajax/facebook-birthdays/' + $("#facebook-token").val(), null, function(result) {
            if (result) {
                $("#facebook-token").addClass('valid').removeClass('wrong');

                $("#output").val("Facebook birthdays:\n\n" + $.toJSON(result));
            }
            else {
                $("#facebook-token").addClass('wrong').removeClass('valid');
                $("#output").val("Dodgy facebook-token or facebook query failed for some other reason >:o");
            }
        });
    });

    $("#scrape-events").click(function(event) {
        event.preventDefault();
        $.getJSON('/ajax/facebook-events/' + $("#facebook-token").val(), null, function(result) {
            if (result) {
                $("#facebook-token").addClass('valid').removeClass('wrong');

                $("#output").val("Facebook events:\n\n" + $.toJSON(result));
            }
            else {
                $("#facebook-token").addClass('wrong').removeClass('valid');
                $("#output").val("Dodgy facebook-token or facebook query failed for some other reason >:o");
            }
        });
    });

    checkSignedRequest();
});
