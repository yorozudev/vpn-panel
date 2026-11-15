import {
  Badge,
  Box,
  Button,
  HStack,
  Icon,
  Progress,
  SimpleGrid,
  Text,
  VStack,
} from "@chakra-ui/react";
import {
  ArrowDownIcon,
  ArrowUpIcon,
  Cog6ToothIcon,
  DevicePhoneMobileIcon,
  ExclamationTriangleIcon,
  UsersIcon,
} from "@heroicons/react/24/outline";
import {
  NodeRealtimeType,
  NodeType,
  useNodesQuery,
  useNodesRealtimeQuery,
} from "contexts/NodesContext";
import { useDashboard } from "contexts/DashboardContext";
import useGetUser from "hooks/useGetUser";
import { FC } from "react";
import { useTranslation } from "react-i18next";
import { NodeModalStatusBadge } from "./NodeModalStatusBadge";

function formatSpeed(bytesPerSecond: number | null) {
  if (bytesPerSecond === null) return "—";
  const bits = bytesPerSecond * 8;
  if (bits >= 1_000_000_000) return `${(bits / 1_000_000_000).toFixed(2)} Гбит/с`;
  if (bits >= 1_000_000) return `${(bits / 1_000_000).toFixed(1)} Мбит/с`;
  if (bits >= 1_000) return `${(bits / 1_000).toFixed(0)} Кбит/с`;
  return `${bits.toFixed(0)} бит/с`;
}

const Meter: FC<{ label: string; value: number | null }> = ({ label, value }) => (
  <Box w="full">
    <HStack justifyContent="space-between" mb={1}>
      <Text fontSize="xs" color="gray.500">{label}</Text>
      <Text fontSize="xs" fontWeight="semibold">
        {value === null ? "—" : `${value.toFixed(1)}%`}
      </Text>
    </HStack>
    <Progress
      value={value ?? 0}
      size="xs"
      w="full"
      colorScheme={value !== null && value >= 85 ? "red" : "blue"}
      borderRadius="full"
      hasStripe={false}
    />
  </Box>
);

const NodeRealtimeCard: FC<{
  node: NodeType;
  realtime?: NodeRealtimeType;
  onSettings: () => void;
}> = ({ node, realtime, onSettings }) => {
  const { t } = useTranslation();
  return (
    <Box
      p={4}
      border="1px solid"
      borderColor="gray.200"
      borderRadius="lg"
      bg="white"
      _dark={{ bg: "gray.800", borderColor: "gray.600" }}
    >
      <HStack justifyContent="space-between" align="flex-start" mb={4}>
        <Box minW={0}>
          <Text fontWeight="semibold" noOfLines={1} title={node.name}>{node.name}</Text>
          <HStack mt={2} spacing={2}>
            <NodeModalStatusBadge status={node.status ?? "error"} compact />
            <Badge
              colorScheme="purple"
              display="inline-flex"
              alignItems="center"
              gap={1}
              title="Активные подписки"
            >
              <Icon as={UsersIcon} w={3} h={3} />
              {realtime?.online_users ?? "—"}
            </Badge>
            <Badge
              colorScheme="blue"
              display="inline-flex"
              alignItems="center"
              gap={1}
              title={
                realtime?.legacy_online_users
                  ? `Устройства; legacy-подключений без отдельного device ID: ${realtime.legacy_online_users}`
                  : "Активные устройства"
              }
            >
              <Icon as={DevicePhoneMobileIcon} w={3} h={3} />
              {realtime?.online_devices ?? "—"}
            </Badge>
            {(realtime?.unattributed_devices ?? 0) > 0 && (
              <Badge
                colorScheme="orange"
                display="inline-flex"
                alignItems="center"
                gap={1}
                title={`Нет маршрута Entry → Exit: подписок ${realtime?.unattributed_users ?? 0}, устройств ${realtime?.unattributed_devices ?? 0}`}
              >
                <Icon as={ExclamationTriangleIcon} w={3} h={3} />
                {realtime?.unattributed_devices}
              </Badge>
            )}
          </HStack>
        </Box>
        <Button size="sm" variant="ghost" onClick={onSettings} aria-label={t("header.nodeSettings")}>
          <Icon as={Cog6ToothIcon} w={5} h={5} />
        </Button>
      </HStack>

      <VStack spacing={3} align="stretch">
        <Meter label="CPU" value={realtime?.cpu_percent ?? null} />
        <Meter label="RAM" value={realtime?.memory_percent ?? null} />
        <HStack justifyContent="space-between" pt={1}>
          <HStack spacing={1} color="green.500">
            <Icon as={ArrowDownIcon} w={4} h={4} />
            <Text fontSize="xs" fontWeight="medium">
              {formatSpeed(realtime?.download_bytes_per_second ?? null)}
            </Text>
          </HStack>
          <HStack spacing={1} color="orange.400">
            <Icon as={ArrowUpIcon} w={4} h={4} />
            <Text fontSize="xs" fontWeight="medium">
              {formatSpeed(realtime?.upload_bytes_per_second ?? null)}
            </Text>
          </HStack>
        </HStack>
      </VStack>
    </Box>
  );
};

export const NodesRealtime: FC = () => {
  const { userData, getUserIsSuccess } = useGetUser();
  const isSudo = getUserIsSuccess && userData.is_sudo;
  const { data: nodes, isLoading } = useNodesQuery();
  const { data: realtime } = useNodesRealtimeQuery(isSudo);
  const { onEditingNodes } = useDashboard();
  const { t } = useTranslation();

  if (!isSudo || isLoading || !nodes?.length) return null;
  const byNodeId = new Map(realtime?.map((item) => [item.node_id, item]));

  return (
    <Box as="section" w="full" mt={4}>
      <HStack justifyContent="space-between" mb={3}>
        <Text fontSize="lg" fontWeight="semibold">
          {t("nodesRealtime.title", { defaultValue: "Мониторинг нод" })}
        </Text>
        <Text fontSize="xs" color="gray.500">
          {t("nodesRealtime.interval", { defaultValue: "Обновление каждые 10 секунд" })}
        </Text>
      </HStack>
      <SimpleGrid columns={{ base: 1, md: 2, xl: 3 }} spacing={4}>
        {nodes.map((node) => (
          <NodeRealtimeCard
            key={node.id}
            node={node}
            realtime={node.id == null ? undefined : byNodeId.get(node.id)}
            onSettings={() => onEditingNodes(true)}
          />
        ))}
      </SimpleGrid>
    </Box>
  );
};
