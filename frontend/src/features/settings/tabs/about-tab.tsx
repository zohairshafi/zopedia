import { Button } from "@/components/ui/button";
import { ShutdownDialog } from "@/components/shutdown-dialog";
import { apiUrl } from "@/lib/api-base";
import {
  ArrowUpRight01Icon,
} from "@hugeicons/core-free-icons";
import { HugeiconsIcon } from "@hugeicons/react";
import { useEffect, useState } from "react";
import { SettingsRow } from "../components/settings-row";
import { SettingsSection } from "../components/settings-section";

function useVersion() {
  const [version, setVersion] = useState<string>("unknown");
  useEffect(() => {
    fetch(apiUrl("/api/health"))
      .then((r) => r.json())
      .then((d: any) => setVersion(d.app || "zopedia"))
      .catch(() => setVersion("zopedia"));
  }, []);
  return version;
}

export function AboutTab() {
  const version = useVersion();
  const [shutdownOpen, setShutdownOpen] = useState(false);

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-lg font-semibold font-heading">About</h1>
        <p className="text-xs text-muted-foreground">
          Zopedia build info and support.
        </p>
      </header>

      <SettingsSection title="Application">
        <SettingsRow label="Version">
          <code className="font-mono text-xs text-muted-foreground">{version}</code>
        </SettingsRow>

        <SettingsRow
          label="Documentation"
          description="Learn how to use Zopedia for your personal wiki and RAG workflows."
        >
          <a
            href="https://github.com/zopedia"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
          >
            GitHub
            <HugeiconsIcon icon={ArrowUpRight01Icon} className="size-3" />
          </a>
        </SettingsRow>
      </SettingsSection>

      <SettingsSection title="Danger zone">
        <SettingsRow
          destructive
          label="Shut down Zopedia"
          description="Stops the Zopedia server process and ends your session."
        >
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShutdownOpen(true)}
            className="text-destructive hover:text-destructive hover:border-destructive/60"
          >
            Shut down now
          </Button>
        </SettingsRow>
      </SettingsSection>

      <ShutdownDialog
        open={shutdownOpen}
        onOpenChange={setShutdownOpen}
        onAfterShutdown={undefined}
      />
    </div>
  );
}
