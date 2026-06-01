from golden_vector.cli import build_parser


def test_update_data_options_flags_default_to_enabled():
    parser = build_parser()

    args = parser.parse_args(["update-data"])

    assert args.command == "update-data"
    assert args.options is True


def test_update_data_no_options_flag_disables_options_phase():
    parser = build_parser()

    args = parser.parse_args(["update-data", "--no-options"])

    assert args.command == "update-data"
    assert args.options is False

