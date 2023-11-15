{ config, pkgs, lib, ... }:

let
  cfg = config.services.ygg-map;
  package = cfg.package;
  inherit (lib) mkIf mkOption mkEnableOption mdDoc literalExpression types;
in
{
  options.services.ygg-map = {
    enable = mkEnableOption (mdDoc "the yggdrasil map service");

    package = mkOption {
      type = types.package;
      default = pkgs.ygg-map;
      defaultText = literalExpression "pkgs.ygg-map";
      description = mdDoc "Yggdrasil map package to use.";
    };

    http = {
      host = mkOption {
        type = types.str;
        default = "127.0.0.1";
        example = "::1";
        description = mdDoc "Only listen to incoming requests on specific IP/host.";
      };

      port = mkOption {
        default = 10200;
        type = types.port;
        description = mdDoc "The port on which to listen.";
      };
    };

    openFirewall = mkOption {
      default = false;
      type = types.bool;
      description = mdDoc "Whether to open the firewall for the specified port.";
    };

    extraArgs = mkOption {
      type = types.listOf types.str;
      default = [ ];
      example = [ ];
      description = mdDoc "Extra cmd for ";
    };
  };
  config = mkIf cfg.enable (
    let

    in
    {
      services.yggdrasil.settings = {
        LogLookups = true;
      };
      networking.firewall.allowedTCPPorts = mkIf cfg.openFirewall [ cfg.http.port ];
      systemd.services.ygg-map = {
        enable = true;
        description = "Yggdrasil map";
        wants = [ "yggdrasil.service" ];
        wantedBy = [ "multi-user.target" ];

        path = with pkgs; [ graphviz ];
        environment = {
          SOCKET = "/var/run/yggdrasil/yggdrasil.sock";
        };
        serviceConfig = {
          ExecStart = "${package.dependencyEnv}/bin/uvicorn app:app --host ${cfg.http.host} --port ${toString cfg.http.port} ${lib.strings.escapeShellArgs cfg.extraArgs}";
          Restart = "on-failure";
          KillSignal = "SIGINT";
          User = "root";
          # DynamicUser = "yes";
        };
      };
    }
  );
}
