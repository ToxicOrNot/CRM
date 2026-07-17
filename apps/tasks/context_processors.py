def task_completion_notice(request):
    undo_data = request.session.get("task_completion_undo")
    if not undo_data or undo_data.get("notice_shown"):
        return {"task_completion_notice": None}

    undo_data["notice_shown"] = True
    request.session["task_completion_undo"] = undo_data
    request.session.modified = True
    return {"task_completion_notice": undo_data}
