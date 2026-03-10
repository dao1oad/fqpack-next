workflow_path =
  System.get_env("SYMPHONY_WORKFLOW_PATH") ||
    raise "SYMPHONY_WORKFLOW_PATH is required"

port =
  case System.get_env("SYMPHONY_SERVICE_PORT") do
    nil ->
      40123

    value ->
      case Integer.parse(value) do
        {parsed, ""} when parsed > 0 -> parsed
        _ -> raise "SYMPHONY_SERVICE_PORT must be a positive integer"
      end
  end

log_file = System.get_env("SYMPHONY_LOG_FILE")

SymphonyElixir.Workflow.set_workflow_file_path(workflow_path)
Application.put_env(:symphony_elixir, :server_port_override, port)

if is_binary(log_file) and String.trim(log_file) != "" do
  Application.put_env(:symphony_elixir, :log_file, log_file)
end

{:ok, _} = Application.ensure_all_started(:symphony_elixir)

IO.puts("[freshquant] symphony started")
IO.puts("[freshquant] workflow=#{workflow_path}")
IO.puts("[freshquant] port=#{port}")

Process.sleep(:infinity)
