function facebook_prompt_permission(permission, callbackFunc) {
    ensure_init(function() {
	//check is user already granted for this permission or not
	FB.Facebook.apiClient.users_hasAppPermission(permission,
	function(result) {
	    // prompt offline permission
	    if (result == 0) {
		// render the permission dialog
		FB.Connect.showPermissionDialog(permission, callbackFunc);
	    } else {
		// permission already granted.
		callbackFunc(true);
	    }
	});
    });
}

